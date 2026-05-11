"""Per-turn reasoning + tool-timing recorder.

Subscribes in parallel with the SSE adapter to the same agent
``EventManager`` and accumulates a small document describing one turn:

- Each chain-of-thought passage (start/delta/end → text + timestamps)
- Each tool call's name, arguments preview, duration, result preview

The recorder is an in-memory listener; only one Mongo write happens at
the end of the turn (``flush()``). It is not on the SSE hot path —
``on_event`` is fast and never awaits Mongo.

Schema lives in ``wiki_tutor_turn_traces`` (see
:mod:`core.conversations_store`). One document per ``run_id``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from events import AgentEvent, EventType
from core.conversations_store import TRACES, ConversationsStore

logger = logging.getLogger(__name__)


_EXTRACTOR_VERSION = "1.0"
_PREVIEW_MAX = 240
_ARGS_DISPLAY_MAX = 200


def _now_ms() -> int:
    return int(time.time() * 1000)


def _format_args_display(name: str, args: Optional[dict[str, Any]]) -> str:
    """Compact one-line representation of tool arguments."""
    if not args:
        return ""
    try:
        # Compact, single-line, key-sorted for stability.
        text = json.dumps(args, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > _ARGS_DISPLAY_MAX:
        text = text[: _ARGS_DISPLAY_MAX - 1] + "…"
    return text


def _format_duration(ms: Optional[float]) -> str:
    if ms is None:
        return ""
    if ms < 1000:
        return f"{int(round(ms))} ms"
    s = ms / 1000.0
    if s < 10:
        return f"{s:.1f} s"
    return f"{int(round(s))} s"


def _truncate(text: str, max_chars: int = _PREVIEW_MAX) -> str:
    if not text:
        return ""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


class TurnTraceRecorder:
    """Listener that accumulates one trace doc per turn."""

    def __init__(
        self,
        *,
        session_id: str,
        user_id: str,
        run_id: str,
        lang: str,
        client_ip: str = "",
    ) -> None:
        self._doc: dict[str, Any] = {
            "_id": run_id,
            "session_id": session_id,
            "user_id": user_id,
            "lang": lang,
            "client_ip": client_ip,
            "started_at": _now_ms(),
            "thoughts": [],
            "tool_timings": [],
            "extractor_version": _EXTRACTOR_VERSION,
        }
        self._active_thought: Optional[dict[str, Any]] = None
        self._active_tools: dict[str, dict[str, Any]] = {}
        self._fallback_tools_by_name: dict[str, list[dict[str, Any]]] = {}
        self._closed = False

    # ── Listener API ──────────────────────────────────────────────────

    async def on_event(self, event: AgentEvent) -> None:
        """Synchronous-ish reducer. Never raises — a recorder bug must
        not break the SSE stream."""
        if self._closed:
            return
        try:
            self._reduce(event)
        except Exception as exc:  # pragma: no cover
            logger.warning("turn_trace_recorder error: %s", exc)

    def _reduce(self, event: AgentEvent) -> None:
        et = event.event_type

        if et == EventType.REASONING_START:
            self._active_thought = {
                "text": "",
                "started_at": _now_ms(),
                "ended_at": None,
            }
            return

        if et == EventType.REASONING_DELTA:
            if self._active_thought is None:
                # Defensive: synthesize an active thought.
                self._active_thought = {
                    "text": "",
                    "started_at": _now_ms(),
                    "ended_at": None,
                }
            if event.content:
                self._active_thought["text"] += event.content
            return

        if et == EventType.REASONING_END:
            if self._active_thought is None:
                return
            self._active_thought["ended_at"] = _now_ms()
            text = (self._active_thought.get("text") or "").strip()
            if text:
                # Only persist non-empty thoughts.
                self._active_thought["text"] = text
                self._doc["thoughts"].append(self._active_thought)
            self._active_thought = None
            return

        if et == EventType.TOOL_START:
            call_id = (event.metadata or {}).get("call_id", "") or ""
            entry: dict[str, Any] = {
                "call_id": call_id,
                "name": event.tool_name or "unknown",
                "arguments_display": _format_args_display(
                    event.tool_name or "", event.tool_arguments
                ),
                "started_at": _now_ms(),
                "ended_at": None,
                "duration_ms": None,
                "duration_display": "",
                "preview": "",
            }
            if call_id:
                self._active_tools[call_id] = entry
            self._fallback_tools_by_name.setdefault(entry["name"], []).append(entry)
            return

        if et == EventType.TOOL_END:
            meta = event.metadata or {}
            call_id = meta.get("call_id", "") or ""
            entry = self._active_tools.pop(call_id, None) if call_id else None
            if entry is None:
                # Fall back to FIFO-by-name (mirrors the SSE adapter).
                queue = self._fallback_tools_by_name.get(event.tool_name or "")
                entry = queue.pop(0) if queue else None
            if entry is None:
                # Synthesize a row so the trace is never silent.
                entry = {
                    "call_id": call_id,
                    "name": event.tool_name or "unknown",
                    "arguments_display": "",
                    "started_at": _now_ms(),
                    "ended_at": None,
                    "duration_ms": None,
                    "duration_display": "",
                    "preview": "",
                }
            ended_at_ms = _now_ms()
            duration_ms = (
                event.duration_ms
                if event.duration_ms is not None
                else max(0, ended_at_ms - entry["started_at"])
            )
            entry["ended_at"] = ended_at_ms
            entry["duration_ms"] = int(duration_ms)
            entry["duration_display"] = _format_duration(duration_ms)
            preview = ""
            result = event.tool_result
            if result is None:
                preview = ""
            elif isinstance(result, str):
                preview = result
            else:
                try:
                    preview = json.dumps(result, ensure_ascii=False)[:_PREVIEW_MAX]
                except (TypeError, ValueError):
                    preview = _truncate(str(result))
            entry["preview"] = _truncate(preview)
            self._doc["tool_timings"].append(entry)
            return

        # Other events (response.*, classification.*, etc.) are ignored —
        # they live on the agno session document.

    # ── Persistence ───────────────────────────────────────────────────

    async def flush(self, store: ConversationsStore) -> None:
        """Write the trace document to Mongo. Idempotent: a re-flushed
        recorder will fail-safe via upsert."""
        if self._closed:
            return
        self._closed = True
        if self._active_thought is not None:
            self._active_thought["ended_at"] = _now_ms()
            text = (self._active_thought.get("text") or "").strip()
            if text:
                self._active_thought["text"] = text
                self._doc["thoughts"].append(self._active_thought)
        # Close any tool that didn't get a TOOL_END (orphaned).
        for entry in list(self._active_tools.values()):
            entry["ended_at"] = _now_ms()
            entry["duration_ms"] = max(0, entry["ended_at"] - entry["started_at"])
            entry["duration_display"] = _format_duration(entry["duration_ms"])
            self._doc["tool_timings"].append(entry)
        self._active_tools.clear()
        self._doc["ended_at"] = _now_ms()

        # Skip the write if there's nothing interesting to record. A turn
        # with no thoughts and no tool calls is just text — agno already
        # has it.
        if not self._doc["thoughts"] and not self._doc["tool_timings"]:
            return
        try:
            await store._db[TRACES].replace_one(
                {"_id": self._doc["_id"]}, self._doc, upsert=True
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("turn_trace flush failed: %s", exc)
