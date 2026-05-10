"""
Event Store - Event sourcing for replay and debugging.

This module provides persistent storage for all events in the system,
enabling full session replay and debugging of parallel agent execution.

Usage:
    from events.store import EventStore, EventRecord

    # Create store with MongoDB collection
    store = EventStore(collection=mongo_pool.get_collection("events"))

    # Append event (assigns sequence number, persists async)
    sequence = await store.append(event, session_id, question_answer_id)

    # Get events for replay
    events = await store.get_session_events(session_id, agent_role="underwriting")

    # Stream replay with timing
    async for event in store.replay_session(session_id, delay_ms=50):
        print(event)
"""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any, AsyncGenerator, TYPE_CHECKING
from pydantic import BaseModel, Field
from loguru import logger

if TYPE_CHECKING:
    from .models import AgentEvent


# ═══════════════════════════════════════════════════════════════════════════
#                    EVENT RECORD MODEL
# ═══════════════════════════════════════════════════════════════════════════

class EventRecord(BaseModel):
    """
    Stored event with metadata for replay and debugging.

    This is the persisted form of an AgentEvent, with additional
    fields for querying and replay.
    """

    # === Event Identification ===
    event_id: str = Field(description="Unique event ID (UUID)")

    # === Session Context ===
    session_id: str = Field(description="Session/conversation ID")
    question_answer_id: str = Field(description="Question-answer pair ID")

    # === Ordering ===
    sequence_number: int = Field(description="Global monotonic sequence for total ordering")
    timestamp: datetime = Field(description="Event creation timestamp")

    # === Event Classification ===
    event_type: str = Field(description="Event type (e.g., 'response.delta')")

    # === Agent Context ===
    agent_role: str = Field(description="Agent role (router, underwriting, origination)")
    agent_run_id: str = Field(default="", description="Unique run ID for this agent's execution")

    # === Correlation ===
    correlation_id: Optional[str] = Field(default=None, description="Groups related events")
    parallel_group_id: Optional[str] = Field(default=None, description="Groups parallel agent events")

    # === Raw Event ===
    raw_event: Dict[str, Any] = Field(default_factory=dict, description="Full serialized AgentEvent")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ═══════════════════════════════════════════════════════════════════════════
#                    EVENT STORE
# ═══════════════════════════════════════════════════════════════════════════

class EventStore:
    """
    Event store with in-memory buffer and async MongoDB persistence.

    Provides:
    - Monotonic sequence number assignment
    - In-memory buffer for fast access
    - Async MongoDB persistence (fire-and-forget)
    - Session replay with timing simulation

    Thread Safety:
    - Uses asyncio.Lock for sequence number assignment
    - Buffer operations are session-isolated

    Usage:
        # Initialize with MongoDB collection
        store = EventStore(collection=mongo_pool.get_collection("events"))

        # Append event
        sequence = await store.append(event, session_id, qa_id)

        # Query events
        events = await store.get_session_events(session_id)

        # Replay
        async for event in store.replay_session(session_id):
            emit_to_client(event)
    """

    def __init__(
        self,
        collection=None,
        buffer_size: int = 1000,
        persist_enabled: bool = True
    ):
        """
        Initialize event store.

        Args:
            collection: MongoDB collection for persistence (optional)
            buffer_size: Max events per session in memory buffer
            persist_enabled: Whether to persist to MongoDB
        """
        self._buffer: Dict[str, List[EventRecord]] = defaultdict(list)
        self._collection = collection
        self._buffer_size = buffer_size
        self._persist_enabled = persist_enabled and collection is not None

        # Global sequence counter with lock for thread safety
        self._sequence = 0
        self._lock = asyncio.Lock()

        # Track active sessions for cleanup
        self._active_sessions: Dict[str, datetime] = {}

        if self._persist_enabled:
            logger.info("[EventStore] Initialized with MongoDB persistence")
        else:
            logger.info("[EventStore] Initialized in-memory only (no persistence)")

    async def append(
        self,
        event: "AgentEvent",
        session_id: str,
        question_answer_id: str
    ) -> int:
        """
        Append event to store.

        Assigns a sequence number, buffers the event, and persists asynchronously.

        Args:
            event: The AgentEvent to store
            session_id: Session/conversation ID
            question_answer_id: Question-answer pair ID

        Returns:
            Assigned sequence number
        """
        # Assign sequence number atomically
        async with self._lock:
            self._sequence += 1
            sequence = self._sequence

        # Create event record
        record = EventRecord(
            event_id=event.event_id,
            session_id=session_id,
            question_answer_id=question_answer_id,
            sequence_number=sequence,
            timestamp=event.timestamp,
            event_type=event.event_type.value,
            agent_role=event.agent_role.value,
            agent_run_id=getattr(event, 'agent_run_id', ''),
            correlation_id=event.correlation_id,
            parallel_group_id=(
                event.parallel_context.parallel_group_id
                if hasattr(event, 'parallel_context') and event.parallel_context
                else None
            ),
            raw_event=event.to_dict()
        )

        # Add to in-memory buffer
        buffer = self._buffer[session_id]
        buffer.append(record)

        # Trim buffer if too large (keep most recent)
        if len(buffer) > self._buffer_size:
            self._buffer[session_id] = buffer[-self._buffer_size:]

        # Track session activity
        self._active_sessions[session_id] = datetime.now()

        # Async persist (fire and forget)
        if self._persist_enabled:
            asyncio.create_task(self._persist(record))

        return sequence

    async def _persist(self, record: EventRecord) -> None:
        """
        Persist event record to MongoDB.

        This is called as a fire-and-forget task to avoid blocking.
        """
        try:
            await self._collection.insert_one(record.model_dump())
        except Exception as e:
            logger.error(f"[EventStore] Persist failed: {e}")

    async def get_session_events(
        self,
        session_id: str,
        agent_role: Optional[str] = None,
        from_sequence: int = 0,
        limit: Optional[int] = None
    ) -> List[EventRecord]:
        """
        Get events for a session.

        Args:
            session_id: Session to retrieve events for
            agent_role: Optional filter by agent role
            from_sequence: Only return events after this sequence number
            limit: Maximum number of events to return

        Returns:
            List of EventRecords, sorted by sequence number
        """
        # First try in-memory buffer
        events = self._buffer.get(session_id, [])

        # If buffer is empty and persistence is enabled, try MongoDB
        if not events and self._persist_enabled:
            events = await self._load_from_mongodb(session_id)

        # Apply filters
        if agent_role:
            events = [e for e in events if e.agent_role == agent_role]

        if from_sequence > 0:
            events = [e for e in events if e.sequence_number > from_sequence]

        # Sort by sequence
        events = sorted(events, key=lambda e: e.sequence_number)

        # Apply limit
        if limit:
            events = events[:limit]

        return events

    async def _load_from_mongodb(self, session_id: str) -> List[EventRecord]:
        """Load events from MongoDB into memory."""
        try:
            cursor = self._collection.find(
                {"session_id": session_id}
            ).sort("sequence_number", 1)

            events = []
            async for doc in cursor:
                # Remove MongoDB _id field
                doc.pop('_id', None)
                events.append(EventRecord(**doc))

            # Cache in buffer
            self._buffer[session_id] = events

            return events
        except Exception as e:
            logger.error(f"[EventStore] MongoDB load failed: {e}")
            return []

    async def replay_session(
        self,
        session_id: str,
        delay_ms: float = 0,
        agent_role: Optional[str] = None
    ) -> AsyncGenerator[EventRecord, None]:
        """
        Replay events for debugging.

        Yields events in sequence order, optionally with timing simulation.

        Args:
            session_id: Session to replay
            delay_ms: Maximum delay between events (simulates timing)
            agent_role: Optional filter by agent role

        Yields:
            EventRecord objects in sequence order
        """
        events = await self.get_session_events(session_id, agent_role=agent_role)

        for i, event in enumerate(events):
            # Apply delay between events (simulating original timing)
            if delay_ms > 0 and i > 0:
                prev_time = events[i - 1].timestamp
                curr_time = event.timestamp

                # Calculate actual delay
                actual_delay = (curr_time - prev_time).total_seconds() * 1000

                # Use minimum of actual delay and max delay
                wait_ms = min(actual_delay, delay_ms)
                if wait_ms > 0:
                    await asyncio.sleep(wait_ms / 1000)

            yield event

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get statistics for a session.

        Returns:
            Dict with event counts by type and agent
        """
        events = self._buffer.get(session_id, [])

        if not events:
            return {"total_events": 0}

        # Count by type
        type_counts: Dict[str, int] = {}
        agent_counts: Dict[str, int] = {}

        for event in events:
            type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1
            agent_counts[event.agent_role] = agent_counts.get(event.agent_role, 0) + 1

        return {
            "total_events": len(events),
            "by_type": type_counts,
            "by_agent": agent_counts,
            "first_sequence": events[0].sequence_number if events else 0,
            "last_sequence": events[-1].sequence_number if events else 0,
            "duration_ms": (
                (events[-1].timestamp - events[0].timestamp).total_seconds() * 1000
                if len(events) > 1 else 0
            )
        }

    def clear_session(self, session_id: str) -> None:
        """Clear in-memory buffer for a session."""
        self._buffer.pop(session_id, None)
        self._active_sessions.pop(session_id, None)

    def clear_inactive_sessions(self, max_age_seconds: int = 3600) -> int:
        """
        Clear sessions older than max_age_seconds.

        Returns:
            Number of sessions cleared
        """
        now = datetime.now()
        cleared = 0

        sessions_to_clear = [
            session_id for session_id, last_activity in self._active_sessions.items()
            if (now - last_activity).total_seconds() > max_age_seconds
        ]

        for session_id in sessions_to_clear:
            self.clear_session(session_id)
            cleared += 1

        if cleared > 0:
            logger.info(f"[EventStore] Cleared {cleared} inactive sessions")

        return cleared

    @property
    def active_session_count(self) -> int:
        """Get count of active sessions in buffer."""
        return len(self._buffer)

    @property
    def total_buffered_events(self) -> int:
        """Get total count of buffered events."""
        return sum(len(events) for events in self._buffer.values())

    def reset_sequence(self) -> None:
        """Reset sequence counter (for testing only)."""
        self._sequence = 0
