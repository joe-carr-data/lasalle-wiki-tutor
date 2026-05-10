"""Base SSE adapter: converts AgentEvents to SSE wire format.

Handles: session lifecycle, reasoning events, tool start/end with
correlation, response delta/end, error/cancel. Subclasses add:
citation processing, graph processing, delegation, stage callbacks
via hooks (_on_response_delta, _on_response_final, _convert_event).

Previously triplicated in text2sql_streaming.py, underwriting_streaming.py,
and origination_streaming.py.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from events import AgentEvent, EventType
from fastapi_sse_contract import (
    SSEEvent,
    SSEEventType,
    SessionStartedEvent,
    SessionEndedEvent,
    AgentThinkingStartEvent,
    AgentThinkingDeltaEvent,
    AgentThinkingEndEvent,
    ToolStartEvent,
    ToolEndEvent,
    FinalResponseStartEvent,
    FinalResponseDeltaEvent,
    FinalResponseEndEvent,
    ResponseFinalEvent,
    ErrorEvent,
    CancelledEvent,
    format_sse,
    get_agent_info,
    format_duration,
    compact_arguments,
)


class BaseSSEAdapter:
    """Base SSE adapter for converting AgentEvents to SSE wire format.

    Provides shared conversion logic for reasoning, tool, response, error,
    and session lifecycle events. Subclasses customize behavior via hooks:

    - ``_on_response_delta(text)`` — transform response text (citations, graphs)
    - ``_on_response_end()`` — called on RESPONSE_END, returns extra SSE events
    - ``_on_response_final(payload)`` — enrich response.final payload
    - ``_convert_event(event_type, event)`` — handle custom event types
    """

    def __init__(
        self,
        *,
        agent_key: str,
        agent_display_name: str,
        query: str,
        session_id: str,
        verbosity: int,
        tool_icons: dict[str, str] | None = None,
        response_origin: str = "",
    ):
        self._agent_key = agent_key
        self._agent_display_name = agent_display_name
        self._query = query
        self._session_id = session_id
        self._verbosity = verbosity
        self._tool_icons = tool_icons or {}
        self._response_origin = response_origin
        self._start_time = time.time()
        self._question_answer_id = str(uuid.uuid4())

        # Reasoning
        self._reasoning_buffer = ""

        # Response
        self._response_buffer = ""
        self._final_response_started = False
        self._final_response_cid: Optional[str] = None
        self._response_ended = False

        # Tools
        self._tool_args_by_call: dict[str, dict] = {}
        self._tools_executed = 0
        self._web_search_used = False

    # ──────────────────────────────────────────────────────────────────
    # Envelope helpers
    # ──────────────────────────────────────────────────────────────────

    def elapsed_ms(self) -> int:
        return int((time.time() - self._start_time) * 1000)

    def _base(self, event_type: SSEEventType, correlation_id: Optional[str] = None) -> dict:
        base = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "elapsed_ms": self.elapsed_ms(),
            "agent": get_agent_info(self._agent_key).model_dump(),
        }
        if correlation_id:
            base["correlation_id"] = correlation_id
        return base

    # ──────────────────────────────────────────────────────────────────
    # Session lifecycle
    # ──────────────────────────────────────────────────────────────────

    def create_session_start(self) -> SessionStartedEvent:
        base = self._base(SSEEventType.SESSION_STARTED, self._question_answer_id)
        return SessionStartedEvent(**base, data={
            "query": self._query,
            "session_id": self._session_id,
            "question_answer_id": self._question_answer_id,
            "verbosity": self._verbosity,
        })

    def create_session_end(self) -> SessionEndedEvent:
        base = self._base(SSEEventType.SESSION_ENDED, self._question_answer_id)
        return SessionEndedEvent(**base, data={
            "query": self._query,
            "session_id": self._session_id,
            "question_answer_id": self._question_answer_id,
            "verbosity": self._verbosity,
            "total_duration_ms": self.elapsed_ms(),
            "total_duration_display": format_duration(self.elapsed_ms()),
            "summary": {
                "agents_used": [self._agent_display_name],
                "tools_executed": self._tools_executed,
                "delegations": 0,
            },
        })

    def create_error(self, error: Exception) -> ErrorEvent:
        base = self._base(SSEEventType.ERROR)
        return ErrorEvent(**base, data={
            "error_type": "system_error",
            "message": str(error),
            "details": repr(error),
            "recoverable": False,
        })

    def create_cancelled(self, query_id: str) -> CancelledEvent:
        base = self._base(SSEEventType.CANCELLED)
        return CancelledEvent(**base, data={
            "query_id": query_id,
            "message": "Query cancelled by user",
            "reason": "user_requested",
        })

    # ──────────────────────────────────────────────────────────────────
    # Response final
    # ──────────────────────────────────────────────────────────────────

    def create_response_final(
        self,
        user_id: str = "",
        company_id: str = "",
        **extra: Any,
    ) -> ResponseFinalEvent:
        base = self._base(SSEEventType.RESPONSE_FINAL)
        payload = {
            "status_code": 200,
            "user_id": user_id,
            "conversation_id": self._session_id,
            "company_id": company_id,
            "question_answer_id": self._question_answer_id,
            "message": {
                "response": self._response_buffer,
                "sources": {},
                "graph": [],
            },
            "message_is_complete": True,
            "response_origin": self._response_origin,
            "web_search_status": "success" if self._web_search_used else "",
            "citation_mode": "uncited",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload.update(extra)
        # Subclass hook to enrich payload (citations, graphs, etc.)
        payload = self._on_response_final(payload)
        return ResponseFinalEvent(**base, data=payload)

    # ──────────────────────────────────────────────────────────────────
    # AgentEvent → SSE conversion
    # ──────────────────────────────────────────────────────────────────

    async def convert(self, event: AgentEvent) -> list[SSEEvent]:
        """Convert an AgentEvent to a list of SSE events.

        Dispatches to the appropriate handler based on event type.
        Calls ``_convert_event()`` hook first — if it returns a list,
        that result is used instead of the default handling.
        """
        t = event.event_type

        # Subclass hook for custom event types (delegation, stage, CTA)
        custom = self._convert_event(t, event)
        if custom is not None:
            return custom

        if t == EventType.REASONING_START:
            return self._convert_reasoning_start(event)
        elif t == EventType.REASONING_DELTA:
            return self._convert_reasoning_delta(event)
        elif t == EventType.REASONING_END:
            return self._convert_reasoning_end(event)
        elif t == EventType.TOOL_START:
            return self._convert_tool_start(event)
        elif t == EventType.TOOL_END:
            return self._convert_tool_end(event)
        elif t == EventType.RESPONSE_DELTA:
            return self._convert_response_delta(event)
        elif t == EventType.RESPONSE_END:
            return self._convert_response_end(event)
        elif t == EventType.ERROR:
            return self._convert_error(event)
        return []

    # ── Reasoning ──────────────────────────────────────────────────────

    def _convert_reasoning_start(self, event: AgentEvent) -> list[SSEEvent]:
        self._reasoning_buffer = ""
        tid = (event.metadata or {}).get("thinking_id", "")
        base = self._base(SSEEventType.AGENT_THINKING_START, correlation_id=tid or None)
        return [AgentThinkingStartEvent(**base, data={"thinking_id": tid})]

    def _convert_reasoning_delta(self, event: AgentEvent) -> list[SSEEvent]:
        delta = event.content or ""
        self._reasoning_buffer += delta
        tid = (event.metadata or {}).get("thinking_id", "")
        base = self._base(SSEEventType.AGENT_THINKING_DELTA, correlation_id=tid or None)
        return [AgentThinkingDeltaEvent(**base, data={
            "thinking_id": tid,
            "delta": delta,
            "accumulated": self._reasoning_buffer,
        })]

    def _convert_reasoning_end(self, event: AgentEvent) -> list[SSEEvent]:
        tid = (event.metadata or {}).get("thinking_id", "")
        duration = self.elapsed_ms()
        base = self._base(SSEEventType.AGENT_THINKING_END, correlation_id=tid or None)
        return [AgentThinkingEndEvent(**base, data={
            "thinking_id": tid,
            "full_text": self._reasoning_buffer,
            "duration_ms": duration,
            "duration_display": format_duration(duration),
        })]

    # ── Tools ──────────────────────────────────────────────────────────

    def _convert_tool_start(self, event: AgentEvent) -> list[SSEEvent]:
        self._tools_executed += 1
        tool_name = event.tool_name or "unknown"
        tool_args = event.tool_arguments or {}
        call_id = (event.metadata or {}).get("call_id", "")
        icon = self._tool_icons.get(tool_name, "🔧")
        args_display = compact_arguments(tool_args) if tool_args else ""

        if call_id:
            self._tool_args_by_call[call_id] = {
                "arguments": tool_args,
                "arguments_display": args_display,
            }

        base = self._base(SSEEventType.TOOL_START, correlation_id=call_id or None)
        return [ToolStartEvent(**base, data={
            "tool": {
                "name": tool_name,
                "call_id": call_id,
                "icon": icon,
                "arguments": tool_args,
                "arguments_display": args_display,
            },
        })]

    def _convert_tool_end(self, event: AgentEvent) -> list[SSEEvent]:
        tool_name = event.tool_name or "unknown"
        meta = event.metadata or {}
        preview = meta.get("result_preview", "")
        call_id = meta.get("call_id", "")
        duration_ms = event.duration_ms or self.elapsed_ms()
        icon = self._tool_icons.get(tool_name, "🔧")

        if tool_name == "web_search":
            self._web_search_used = True

        stored = self._tool_args_by_call.pop(call_id, {})
        tool_args = stored.get("arguments", {})
        args_display = stored.get("arguments_display", "")

        base = self._base(SSEEventType.TOOL_END, correlation_id=call_id or None)
        return [ToolEndEvent(**base, data={
            "tool": {
                "name": tool_name,
                "call_id": call_id,
                "icon": icon,
                "arguments": tool_args,
                "arguments_display": args_display,
            },
            "duration_ms": duration_ms,
            "duration_display": format_duration(duration_ms),
            "result_preview": preview[:5000] if preview else "",
            "success": meta.get("success", True),
            "orphaned": False,
        })]

    # ── Response ───────────────────────────────────────────────────────

    def _convert_response_delta(self, event: AgentEvent) -> list[SSEEvent]:
        events: list[SSEEvent] = []

        # Iteration reset
        if self._final_response_started and self._response_ended:
            self._response_buffer = ""
            self._response_ended = False
            self._final_response_cid = str(uuid.uuid4())
            start_base = self._base(SSEEventType.FINAL_RESPONSE_START, self._final_response_cid)
            events.append(FinalResponseStartEvent(**start_base, data={}))

        raw_delta = event.content or ""

        # Subclass hook for citation/graph processing
        processed_delta, extra_events = self._on_response_delta(raw_delta)
        events.extend(extra_events)

        self._response_buffer += processed_delta

        # final_response.start on first delta
        if not self._final_response_started:
            self._final_response_started = True
            self._final_response_cid = str(uuid.uuid4())
            start_base = self._base(SSEEventType.FINAL_RESPONSE_START, self._final_response_cid)
            events.append(FinalResponseStartEvent(**start_base, data={}))

        # final_response.delta
        delta_base = self._base(SSEEventType.FINAL_RESPONSE_DELTA, self._final_response_cid)
        events.append(FinalResponseDeltaEvent(**delta_base, data={
            "delta": processed_delta,
            "accumulated": self._response_buffer,
        }))
        return events

    def _convert_response_end(self, event: AgentEvent) -> list[SSEEvent]:
        events: list[SSEEvent] = []

        # Subclass hook for flush (graph processor, citation flush, etc.)
        extra = self._on_response_end()
        events.extend(extra)

        if self._final_response_started:
            self._response_ended = True
            base = self._base(SSEEventType.FINAL_RESPONSE_END, self._final_response_cid)
            events.append(FinalResponseEndEvent(**base, data={
                "full_text": self._response_buffer,
                "duration_ms": self.elapsed_ms(),
                "duration_display": format_duration(self.elapsed_ms()),
            }))
        return events

    # ── Error ──────────────────────────────────────────────────────────

    def _convert_error(self, event: AgentEvent) -> list[SSEEvent]:
        base = self._base(SSEEventType.ERROR)
        return [ErrorEvent(**base, data={
            "error_type": "agent_error",
            "message": event.content or "Unknown error",
            "details": "",
            "recoverable": False,
        })]

    # ──────────────────────────────────────────────────────────────────
    # Subclass hooks
    # ──────────────────────────────────────────────────────────────────

    def _on_response_delta(self, text: str) -> tuple[str, list[SSEEvent]]:
        """Hook for response text processing (citations, graphs).

        Returns (processed_text, extra_sse_events). Default: pass-through.
        """
        return text, []

    def _on_response_end(self) -> list[SSEEvent]:
        """Hook called on RESPONSE_END. Returns extra SSE events (e.g., graph flush).

        Default: no extra events.
        """
        return []

    def _on_response_final(self, payload: dict) -> dict:
        """Hook to enrich the response.final payload (citations, graphs).

        Default: pass-through.
        """
        return payload

    def _convert_event(self, event_type: EventType, event: AgentEvent) -> list[SSEEvent] | None:
        """Generic per-event-type hook for custom event handling.

        Return ``list[SSEEvent]`` to override default conversion for this
        event type, or ``None`` to fall through to default handling.

        Enables subclasses to handle delegation, stage-thinking, CTA, or
        any future event types without modifying the base class.
        """
        return None
