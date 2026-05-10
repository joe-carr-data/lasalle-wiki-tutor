"""Shared cancellation registry for SSE streaming endpoints.

Provides cooperative cancellation for long-running streaming queries.
Previously triplicated in text2sql_streaming.py, underwriting_streaming.py,
and origination_streaming.py.
"""

from __future__ import annotations

import asyncio
from typing import Dict

_active_queries: Dict[str, asyncio.Event] = {}
_active_queries_lock = asyncio.Lock()


async def register_query(query_id: str) -> asyncio.Event:
    """Register a query for cancellation support. Returns the cancel event."""
    async with _active_queries_lock:
        event = asyncio.Event()
        _active_queries[query_id] = event
        return event


async def unregister_query(query_id: str) -> None:
    """Remove a query from the cancellation registry."""
    async with _active_queries_lock:
        _active_queries.pop(query_id, None)


async def cancel_query(query_id: str) -> bool:
    """Signal cancellation for a query. Returns True if found."""
    async with _active_queries_lock:
        event = _active_queries.get(query_id)
        if event:
            event.set()
            return True
        return False
