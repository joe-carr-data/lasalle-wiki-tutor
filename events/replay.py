"""
Event Replay - API utilities for event replay and debugging.

This module provides functions for replaying stored events,
designed to be used by FastAPI routes in the backend service.

Usage:
    from events.replay import (
        get_session_events_for_api,
        get_session_stats_for_api,
        replay_session_stream
    )

    # In FastAPI route
    @router.get("/events/{session_id}")
    async def get_events(session_id: str, store: EventStore = Depends(get_event_store)):
        return await get_session_events_for_api(store, session_id)
"""

from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime
from loguru import logger

from .store import EventStore, EventRecord


async def get_session_events_for_api(
    store: EventStore,
    session_id: str,
    agent_role: Optional[str] = None,
    from_sequence: int = 0,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get events for a session, formatted for API response.

    Args:
        store: EventStore instance
        session_id: Session ID to retrieve events for
        agent_role: Optional filter by agent role
        from_sequence: Only return events after this sequence number
        limit: Maximum number of events to return

    Returns:
        Dict with events and metadata for API response
    """
    try:
        events = await store.get_session_events(
            session_id=session_id,
            agent_role=agent_role,
            from_sequence=from_sequence,
            limit=limit
        )

        return {
            "session_id": session_id,
            "event_count": len(events),
            "from_sequence": from_sequence,
            "events": [_event_to_api_format(e) for e in events],
            "filters": {
                "agent_role": agent_role,
                "from_sequence": from_sequence,
                "limit": limit
            }
        }
    except Exception as e:
        logger.error(f"[EventReplay] Failed to get session events: {e}")
        return {
            "session_id": session_id,
            "event_count": 0,
            "events": [],
            "error": str(e)
        }


async def get_session_stats_for_api(
    store: EventStore,
    session_id: str
) -> Dict[str, Any]:
    """
    Get session statistics for API response.

    Args:
        store: EventStore instance
        session_id: Session ID to get stats for

    Returns:
        Dict with session statistics
    """
    stats = store.get_session_stats(session_id)

    return {
        "session_id": session_id,
        **stats
    }


async def replay_session_stream(
    store: EventStore,
    session_id: str,
    delay_ms: float = 0,
    agent_role: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Replay events as a stream for SSE.

    Args:
        store: EventStore instance
        session_id: Session ID to replay
        delay_ms: Maximum delay between events (simulates timing)
        agent_role: Optional filter by agent role

    Yields:
        Event dicts formatted for SSE
    """
    async for event in store.replay_session(
        session_id=session_id,
        delay_ms=delay_ms,
        agent_role=agent_role
    ):
        yield _event_to_api_format(event)


def _event_to_api_format(record: EventRecord) -> Dict[str, Any]:
    """
    Convert EventRecord to API response format.

    Args:
        record: EventRecord from store

    Returns:
        Dict formatted for API response
    """
    return {
        "event_id": record.event_id,
        "sequence_number": record.sequence_number,
        "timestamp": record.timestamp.isoformat(),
        "event_type": record.event_type,
        "agent_role": record.agent_role,
        "agent_run_id": record.agent_run_id,
        "correlation_id": record.correlation_id,
        "parallel_group_id": record.parallel_group_id,
        "raw_event": record.raw_event
    }


# ═══════════════════════════════════════════════════════════════════════════
# Example FastAPI Route Integration
# ═══════════════════════════════════════════════════════════════════════════
#
# from fastapi import APIRouter, Depends, Query
# from fastapi.responses import StreamingResponse
# from events.replay import (
#     get_session_events_for_api,
#     get_session_stats_for_api,
#     replay_session_stream
# )
# from events.store import EventStore
#
# router = APIRouter(prefix="/events", tags=["events"])
#
# @router.get("/{session_id}")
# async def get_events(
#     session_id: str,
#     agent_role: Optional[str] = Query(None),
#     from_sequence: int = Query(0),
#     limit: Optional[int] = Query(None),
#     store: EventStore = Depends(get_event_store)
# ):
#     return await get_session_events_for_api(
#         store, session_id, agent_role, from_sequence, limit
#     )
#
# @router.get("/{session_id}/stats")
# async def get_stats(
#     session_id: str,
#     store: EventStore = Depends(get_event_store)
# ):
#     return await get_session_stats_for_api(store, session_id)
#
# @router.get("/{session_id}/replay")
# async def replay_events(
#     session_id: str,
#     delay_ms: float = Query(50.0),
#     agent_role: Optional[str] = Query(None),
#     store: EventStore = Depends(get_event_store)
# ):
#     async def event_generator():
#         async for event in replay_session_stream(
#             store, session_id, delay_ms, agent_role
#         ):
#             yield f"data: {json.dumps(event)}\n\n"
#
#     return StreamingResponse(
#         event_generator(),
#         media_type="text/event-stream"
#     )
