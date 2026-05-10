"""Base class for single-agent streaming executors with OpenAI event interception.

Handles: OpenAI stream → AgentEvent conversion, parallel tool tracking,
JSON response field extraction, reasoning events, drain/flush/cleanup lifecycle.

Subclasses implement: async_setup(), run(), and optionally override
on_tool_result() for tool-specific result attachment.

NOT for multi-agent orchestration (LQCDataTeam) — that has fundamentally
different event handling with lane-based reasoning and delegation tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from core.openai_event_interceptor import (
    OpenAIEventInterceptor,
    patch_openai_responses_streaming,
    set_session_context,
    unpatch_openai_responses_streaming,
)
from events import AgentEvent, EventType
from events.manager import EventManager
from events.models import AgentRole

logger = logging.getLogger(__name__)


class BaseStreamingAgent(ABC):
    """Abstract base for streaming agents with OpenAI event interception.

    Provides:
    - OpenAI stream event interception via monkey-patching
    - Parallel-safe tool tracking (``_active_tools`` dict, ``_item_id_to_call_id`` mapping)
    - Reasoning event lifecycle (start/delta/end)
    - JSON structured-output response field extraction
    - call_id-aware tool result callback with FIFO fallback
    - Drain/flush/cleanup lifecycle

    Subclasses must implement ``async_setup()`` and ``run()``.
    """

    # JSON key to extract from structured output (override if different)
    _RESPONSE_KEY = '"response":"'

    def __init__(
        self,
        *,
        agent_role: AgentRole,
        agent_name: str,
        session_id: str,
        user_id: str = "",
        tool_result_queues: dict[str, list] | None = None,
    ):
        # Agent identity (injected, not hardcoded)
        self._agent_role = agent_role
        self._agent_name = agent_name
        self.session_id = session_id
        self.user_id = user_id

        # Event infrastructure
        self.event_manager = EventManager()
        self._openai_interceptor: Optional[OpenAIEventInterceptor] = None
        self._openai_event_queue: asyncio.Queue = asyncio.Queue()
        self._drain_task: Optional[asyncio.Task] = None

        # Parallel-safe tool tracking
        self._pending_tool_calls: dict[str, dict] = {}
        self._last_added_tool: Optional[dict] = None
        self._item_id_to_call_id: dict[str, str] = {}
        self._active_tools: dict[str, dict] = {}  # call_id → {name, call_id, started_at}
        self._tool_result_queues: dict[str, list] = tool_result_queues or {}

        # Reasoning state
        self._reasoning_active = False
        self._reasoning_item_id = ""

        # JSON response parsing state
        self._json_buffer = ""
        self._in_response_field = False
        self._escape_carry = ""

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    def setup(self) -> None:
        """Patch OpenAI streaming to intercept assistant's events."""
        self._openai_interceptor = OpenAIEventInterceptor(enable_logging=False)
        queue = self._openai_event_queue

        @self._openai_interceptor.on("*")
        def forward_openai_event(event):
            event._captured_at = time.time()
            try:
                queue.put_nowait(event)
            except Exception:
                pass

        self._drain_task = asyncio.create_task(self._drain_openai_events())
        patch_openai_responses_streaming(self._openai_interceptor, self.session_id)
        set_session_context(self.session_id)
        logger.info(
            "[%s] Setup complete (session=%s)", self._agent_name, self.session_id[:8],
        )

    async def flush_events(self) -> None:
        """Flush remaining OpenAI events before finishing."""
        await self._emit_tool_end_if_pending()
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None

    async def cleanup(self) -> None:
        """Release all resources."""
        await self.flush_events()
        try:
            unpatch_openai_responses_streaming(self.session_id)
        except Exception as e:
            logger.warning("[%s] Error unpatching interceptor: %s", self._agent_name, e)
        # Agent-specific cleanup hook
        await self._on_cleanup()
        logger.info("[%s] Cleanup complete (session=%s)", self._agent_name, self.session_id[:8])

    # ──────────────────────────────────────────────────────────────────
    # OpenAI event drain
    # ──────────────────────────────────────────────────────────────────

    async def _drain_openai_events(self) -> None:
        """Background task: process OpenAI events from queue in order."""
        try:
            while True:
                event = await self._openai_event_queue.get()
                try:
                    await self._handle_openai_event(event)
                except Exception as e:
                    logger.error(
                        "[%s] Error handling OpenAI event: %s", self._agent_name, e,
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            while not self._openai_event_queue.empty():
                try:
                    event = self._openai_event_queue.get_nowait()
                    await self._handle_openai_event(event)
                except Exception:
                    break

    # ──────────────────────────────────────────────────────────────────
    # Tool end emission (parallel-safe)
    # ──────────────────────────────────────────────────────────────────

    async def _emit_tool_end_if_pending(self) -> None:
        """Emit TOOL_END for ALL active tools (handles parallel tool calls)."""
        if not self._active_tools:
            return
        tools_to_close = list(self._active_tools.values())
        self._active_tools.clear()
        for tool_info in tools_to_close:
            duration_ms = int((time.time() - tool_info.get("started_at", 0)) * 1000)
            meta: dict[str, Any] = {"call_id": tool_info.get("call_id", ""), "success": True}
            tool_name = tool_info.get("name", "unknown")
            # Attach queued result preview if available
            queue = self._tool_result_queues.get(tool_name)
            if queue:
                meta["result_preview"] = queue.pop(0)
            await self.event_manager.emit(AgentEvent(
                event_type=EventType.TOOL_END,
                agent_role=self._agent_role,
                agent_name=self._agent_name,
                tool_name=tool_name,
                duration_ms=duration_ms,
                session_id=self.session_id,
                metadata=meta,
            ))

    # ──────────────────────────────────────────────────────────────────
    # OpenAI event dispatch
    # ──────────────────────────────────────────────────────────────────

    async def _handle_openai_event(self, event: Any) -> None:
        """Convert OpenAI stream events to AgentEvents and emit."""
        event_type = getattr(event, "type", "")

        if event_type == "response.created":
            await self._emit_tool_end_if_pending()
            self._reasoning_active = False
            self._reasoning_item_id = ""
            # Prune stale correlation state from previous round
            self._pending_tool_calls.clear()
            self._item_id_to_call_id.clear()
            self._last_added_tool = None

        elif event_type == "response.reasoning_summary_text.delta":
            await self._emit_tool_end_if_pending()
            if not self._reasoning_active:
                self._reasoning_active = True
                self._reasoning_item_id = getattr(event, "item_id", "")
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.REASONING_START,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                    metadata={"thinking_id": self._reasoning_item_id},
                ))
            delta = getattr(event, "delta", "")
            if delta:
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.REASONING_DELTA,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    content=delta,
                    session_id=self.session_id,
                    metadata={"thinking_id": self._reasoning_item_id},
                ))

        elif event_type == "response.reasoning_summary_text.done":
            self._reasoning_active = False
            await self.event_manager.emit(AgentEvent(
                event_type=EventType.REASONING_END,
                agent_role=self._agent_role,
                agent_name=self._agent_name,
                session_id=self.session_id,
                metadata={"thinking_id": self._reasoning_item_id},
            ))

        elif event_type == "response.output_item.added":
            item = getattr(event, "item", None)
            item_type = getattr(item, "type", "") if item else ""

            if item_type == "reasoning":
                await self._emit_tool_end_if_pending()
                self._reasoning_active = True
                self._reasoning_item_id = getattr(item, "id", "") or ""
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.REASONING_START,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                    metadata={"thinking_id": self._reasoning_item_id},
                ))

            elif item_type == "function_call":
                tool_name = getattr(item, "name", "") or "unknown"
                call_id = getattr(item, "call_id", "") or ""
                item_id = getattr(item, "id", "") or ""
                key = call_id or item_id
                if key:
                    self._pending_tool_calls[key] = {"name": tool_name, "emitted_start": False}
                if item_id and call_id:
                    self._item_id_to_call_id[item_id] = call_id
                self._last_added_tool = {"name": tool_name, "call_id": call_id, "item_id": item_id}

        elif event_type == "response.output_item.done":
            item = getattr(event, "item", None)
            item_type = getattr(item, "type", "") if item else ""
            if item_type == "reasoning" and self._reasoning_active:
                self._reasoning_active = False
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.REASONING_END,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                    metadata={"thinking_id": self._reasoning_item_id},
                ))

        elif event_type == "response.function_call_arguments.done":
            # Use item_id → call_id mapping (reliable for parallel tools)
            event_call_id = getattr(event, "call_id", "") or ""
            item_id = getattr(event, "item_id", "") or ""
            mapped_call_id = self._item_id_to_call_id.get(item_id, "")
            stored_call_id = self._last_added_tool.get("call_id", "") if self._last_added_tool else ""
            call_id = event_call_id or mapped_call_id or stored_call_id

            tracked = (
                self._pending_tool_calls.get(call_id)
                or self._pending_tool_calls.get(item_id)
                or {}
            )
            if not tracked and self._last_added_tool:
                tool_name = self._last_added_tool["name"]
                self._last_added_tool = None
            else:
                tool_name = tracked.get("name") or "unknown"

            args_str = getattr(event, "arguments", "") or ""
            try:
                tool_args = json.loads(args_str) if args_str else {}
            except (json.JSONDecodeError, TypeError):
                tool_args = {"raw": args_str} if args_str else {}

            key = call_id or item_id
            effective_call_id = key
            if key:
                self._pending_tool_calls[key] = {"name": tool_name, "emitted_start": True}
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.TOOL_START,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    tool_name=tool_name,
                    tool_arguments=tool_args,
                    session_id=self.session_id,
                    metadata={"call_id": effective_call_id},
                ))
                self._active_tools[effective_call_id] = {
                    "name": tool_name,
                    "call_id": effective_call_id,
                    "started_at": time.time(),
                }

        elif event_type == "response.output_text.delta":
            await self._emit_tool_end_if_pending()
            delta = getattr(event, "delta", "")
            if delta:
                await self._handle_json_response_delta(delta)

        elif event_type == "response.output_text.done":
            if self._in_response_field:
                self._in_response_field = False
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.RESPONSE_END,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                ))
            self._json_buffer = ""

    # ──────────────────────────────────────────────────────────────────
    # JSON response field extraction
    # ──────────────────────────────────────────────────────────────────

    async def _handle_json_response_delta(self, delta: str) -> None:
        """Extract the ``response`` field from streaming JSON structured output.

        Accumulates deltas in ``_json_buffer`` until the ``"response":"`` key
        is found, then streams the value token-by-token as RESPONSE_DELTA
        events. Handles JSON escape sequences split across chunk boundaries.
        """
        if self._in_response_field:
            chunk = self._escape_carry + delta
            self._escape_carry = ""

            i = 0
            end_idx = -1
            while i < len(chunk):
                if chunk[i] == "\\":
                    i += 2
                elif chunk[i] == '"':
                    end_idx = i
                    break
                else:
                    i += 1

            if end_idx != -1:
                raw = chunk[:end_idx]
                self._in_response_field = False
            else:
                raw = chunk
                if raw.endswith("\\") and not raw.endswith("\\\\"):
                    self._escape_carry = "\\"
                    raw = raw[:-1]

            if raw:
                try:
                    text = json.loads(f'"{raw}"')
                except (json.JSONDecodeError, ValueError):
                    text = raw
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.RESPONSE_DELTA,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    content=text,
                    session_id=self.session_id,
                ))

            if end_idx != -1:
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.RESPONSE_END,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                ))
        else:
            self._json_buffer += delta
            idx = self._json_buffer.find(self._RESPONSE_KEY)
            if idx != -1:
                self._in_response_field = True
                remainder = self._json_buffer[idx + len(self._RESPONSE_KEY):]
                self._json_buffer = ""
                if remainder:
                    await self._handle_json_response_delta(remainder)

    # ──────────────────────────────────────────────────────────────────
    # Tool result callback (call_id-aware)
    # ──────────────────────────────────────────────────────────────────

    async def on_tool_result(
        self, tool_name: str, summary: str, call_id: str | None = None,
    ) -> None:
        """Generic tool result callback — emits TOOL_END or queues for later.

        Matches active tools by ``call_id`` first (exact), then by ``tool_name``
        (oldest FIFO match). If no active tool matches, queues the result for
        attachment by ``_emit_tool_end_if_pending()``.

        Subclasses can override for custom behavior (e.g., draining the OpenAI
        event queue before matching, as the hint tool does).
        """
        # Drain any pending OpenAI events so _active_tools is populated
        while not self._openai_event_queue.empty():
            try:
                event = self._openai_event_queue.get_nowait()
                await self._handle_openai_event(event)
            except Exception:
                break

        # Priority 1: exact call_id match
        matched_cid = None
        if call_id and call_id in self._active_tools:
            matched_cid = call_id
        # Priority 2: first matching tool name (FIFO)
        if not matched_cid:
            for cid, info in self._active_tools.items():
                if info.get("name") == tool_name:
                    matched_cid = cid
                    break
        if matched_cid:
            tool_info = self._active_tools.pop(matched_cid)
            duration_ms = int((time.time() - tool_info.get("started_at", 0)) * 1000)
            await self.event_manager.emit(AgentEvent(
                event_type=EventType.TOOL_END,
                agent_role=self._agent_role,
                agent_name=self._agent_name,
                tool_name=tool_name,
                duration_ms=duration_ms,
                session_id=self.session_id,
                metadata={
                    "call_id": tool_info.get("call_id", ""),
                    "success": True,
                    "result_preview": summary,
                },
            ))
        else:
            # Queue for later attachment by _emit_tool_end_if_pending
            self._tool_result_queues.setdefault(tool_name, []).append(summary)

    # ──────────────────────────────────────────────────────────────────
    # Subclass hooks
    # ──────────────────────────────────────────────────────────────────

    @abstractmethod
    async def async_setup(self) -> None:
        """Initialize agent-specific resources (pipeline, tools, MCP session)."""

    @abstractmethod
    async def run(self, question: str) -> dict[str, Any]:
        """Execute the agent and return the result dict."""

    async def _on_cleanup(self) -> None:
        """Override for agent-specific cleanup (close pipeline, neo4j client, etc.)."""
