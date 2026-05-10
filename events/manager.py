"""
Event Manager - Centralized event emission and subscription

This module provides the EventManager class which manages event creation,
emission, and callbacks. It handles timing, parent/child relationships,
and provides convenience methods for all event types.
"""

import time
import uuid
from utils.logger import logger
from typing import Optional, Callable, Awaitable, List, Dict, Any
from datetime import datetime

from .models import AgentEvent, EventType, AgentRole, get_agent_name

class EventManager:
    """
    Manages event creation, tracking, and callbacks.

    The EventManager is responsible for:
    - Creating events with proper timestamps
    - Tracking start/end event pairs
    - Emitting events to subscribers
    - Managing event timing

    Example:
        >>> manager = EventManager()
        >>> manager.subscribe(console_callback)
        >>> await manager.emit_reasoning_start(AgentRole.ROUTER)
        >>> await manager.emit_reasoning_delta(AgentRole.ROUTER, "Thinking...")
        >>> await manager.emit_reasoning_end(AgentRole.ROUTER)
    """

    def __init__(self):
        """Initialize the event manager"""
        # Callbacks (subscribers)
        self._callbacks: List[Callable[[AgentEvent], Awaitable[None]]] = []

        # Active events for start/end pairing
        # Key format: "{event_type}_{agent_role}_{identifier}"
        self._active_events: Dict[str, Dict[str, Any]] = {}

        # Start times for duration calculation
        # Key format: same as _active_events
        self._start_times: Dict[str, float] = {}

    # ============================================
    # Subscription Management
    # ============================================

    def subscribe(self, callback: Callable[[AgentEvent], Awaitable[None]]):
        """
        Subscribe to all events.

        Args:
            callback: Async function that receives AgentEvent objects

        Example:
            >>> async def my_callback(event: AgentEvent):
            ...     print(f"Event: {event.event_type}")
            >>> manager.subscribe(my_callback)
        """
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[AgentEvent], Awaitable[None]]):
        """
        Unsubscribe from events.

        Args:
            callback: The callback function to remove
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def emit(self, event: AgentEvent):
        """
        Emit an event to all subscribers.

        Args:
            event: The event to emit

        Note:
            Errors in callbacks are logged but don't stop other callbacks.
        """
        for callback in self._callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}", exc_info=True)

    # ============================================
    # Reasoning Events
    # ============================================

    async def emit_reasoning_start(self, agent_role: AgentRole, thinking_id: Optional[str] = None) -> str:
        """
        Emit reasoning start event.

        Args:
            agent_role: Which agent is reasoning
            thinking_id: OpenAI's item_id (rs_XXX format) for correlating start/delta/end events

        Returns:
            Event ID (for parent/child relationships)
        """
        event_id = str(uuid.uuid4())
        key = f"reasoning_{thinking_id or agent_role.value}"

        # Store start time
        self._start_times[key] = time.time()

        # Store event info
        self._active_events[key] = {
            "event_id": event_id,
            "start_time": self._start_times[key],
            "thinking_id": thinking_id
        }

        event = AgentEvent(
            event_type=EventType.REASONING_START,
            event_id=event_id,
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            metadata={"thinking_id": thinking_id} if thinking_id else {},
        )

        await self.emit(event)
        return event_id

    async def emit_reasoning_delta(self, agent_role: AgentRole, content: str, thinking_id: Optional[str] = None):
        """
        Emit reasoning delta event (streaming content).

        Args:
            agent_role: Which agent is reasoning
            content: Reasoning text chunk
            thinking_id: OpenAI's item_id (rs_XXX format) for correlating start/delta/end events
        """
        key = f"reasoning_{thinking_id or agent_role.value}"
        active_event = self._active_events.get(key, {})
        parent_id = active_event.get("event_id")
        # Use stored thinking_id if not provided
        thinking_id = thinking_id or active_event.get("thinking_id")

        event = AgentEvent(
            event_type=EventType.REASONING_DELTA,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            content=content,
            parent_event_id=parent_id,
            metadata={"thinking_id": thinking_id} if thinking_id else {},
        )

        await self.emit(event)

    async def emit_reasoning_end(self, agent_role: AgentRole, thinking_id: Optional[str] = None):
        """
        Emit reasoning end event.

        Args:
            agent_role: Which agent finished reasoning
            thinking_id: OpenAI's item_id (rs_XXX format) for correlating start/delta/end events
        """
        key = f"reasoning_{thinking_id or agent_role.value}"
        start_info = self._active_events.pop(key, None)
        start_time = self._start_times.pop(key, None)

        # Use stored thinking_id if not provided
        thinking_id = thinking_id or (start_info.get("thinking_id") if start_info else None)

        # Calculate duration
        duration_ms = None
        if start_time is not None:
            duration_ms = (time.time() - start_time) * 1000

        event = AgentEvent(
            event_type=EventType.REASONING_END,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            duration_ms=duration_ms,
            parent_event_id=start_info.get("event_id") if start_info else None,
            metadata={"thinking_id": thinking_id} if thinking_id else {},
        )

        await self.emit(event)

    # ============================================
    # Arguments Events
    # ============================================

    async def emit_arguments_start(
        self,
        agent_role: AgentRole,
        tool_name: str
    ) -> str:
        """
        Emit arguments start event.

        Args:
            agent_role: Which agent is calling the tool
            tool_name: Name of the tool being called

        Returns:
            Event ID
        """
        event_id = str(uuid.uuid4())
        key = f"arguments_{agent_role.value}_{tool_name}"

        self._start_times[key] = time.time()
        self._active_events[key] = {
            "event_id": event_id,
            "start_time": self._start_times[key]
        }

        event = AgentEvent(
            event_type=EventType.ARGUMENTS_START,
            event_id=event_id,
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            tool_name=tool_name,
        )

        await self.emit(event)
        return event_id

    async def emit_arguments_delta(
        self,
        agent_role: AgentRole,
        tool_name: str,
        content: str
    ):
        """
        Emit arguments delta event (streaming arguments).

        Args:
            agent_role: Which agent is calling the tool
            tool_name: Name of the tool
            content: Arguments JSON chunk
        """
        key = f"arguments_{agent_role.value}_{tool_name}"
        parent_id = self._active_events.get(key, {}).get("event_id")

        event = AgentEvent(
            event_type=EventType.ARGUMENTS_DELTA,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            tool_name=tool_name,
            content=content,
            parent_event_id=parent_id
        )

        await self.emit(event)

    async def emit_arguments_end(
        self,
        agent_role: AgentRole,
        tool_name: str,
        arguments: Optional[Dict] = None
    ):
        """
        Emit arguments end event.

        Args:
            agent_role: Which agent called the tool
            tool_name: Name of the tool
            arguments: Parsed arguments (optional)
        """
        key = f"arguments_{agent_role.value}_{tool_name}"
        start_info = self._active_events.pop(key, None)
        start_time = self._start_times.pop(key, None)

        duration_ms = None
        if start_time is not None:
            duration_ms = (time.time() - start_time) * 1000

        event = AgentEvent(
            event_type=EventType.ARGUMENTS_END,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            tool_name=tool_name,
            tool_arguments=arguments,
            duration_ms=duration_ms,
            parent_event_id=start_info.get("event_id") if start_info else None
        )

        await self.emit(event)

    # ============================================
    # Tool Events
    # ============================================

    async def emit_tool_start(
        self,
        agent_role: AgentRole,
        tool_name: str,
        arguments: Optional[Dict] = None,
        call_id: Optional[str] = None
    ) -> str:
        """
        Emit tool start event.

        Args:
            agent_role: Which agent is calling the tool
            tool_name: Name of the tool
            arguments: Tool arguments
            call_id: Unique call ID (from OpenAI)

        Returns:
            Event ID
        """
        event_id = str(uuid.uuid4())
        key = f"tool_{call_id or tool_name}"

        self._start_times[key] = time.time()
        self._active_events[key] = {
            "event_id": event_id,
            "start_time": self._start_times[key],
            "agent_role": agent_role,
            "tool_name": tool_name,
            "tool_arguments": arguments  # Store for tool.end key parity
        }

        event = AgentEvent(
            event_type=EventType.TOOL_START,
            event_id=event_id,
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            tool_name=tool_name,
            tool_arguments=arguments,
            metadata={"call_id": call_id} if call_id else {},
        )

        await self.emit(event)
        return event_id

    async def emit_tool_end(
        self,
        agent_role: Optional[AgentRole],
        tool_name: str,
        result: Optional[Any] = None,
        call_id: Optional[str] = None,
        override_duration_ms: Optional[float] = None,
        orphaned: bool = False
    ):
        """
        Emit tool end event.

        Args:
            agent_role: Which agent called the tool (can be inferred from start)
            tool_name: Name of the tool
            result: Tool execution result
            call_id: Unique call ID (from OpenAI)
            override_duration_ms: Override calculated duration with actual execution time from RunEvent metrics
            orphaned: True if this is a cleanup emission for a tool that never received ToolCallCompletedEvent
        """
        key = f"tool_{call_id or tool_name}"
        start_info = self._active_events.pop(key, None)
        start_time = self._start_times.pop(key, None)

        # Get agent from start event if not provided
        if agent_role is None and start_info:
            agent_role = start_info.get("agent_role", AgentRole.ROUTER)
        elif agent_role is None:
            agent_role = AgentRole.ROUTER

        # Use override_duration_ms if provided (from RunEvent metrics), otherwise calculate
        if override_duration_ms is not None:
            duration_ms = override_duration_ms
        elif start_time is not None:
            duration_ms = (time.time() - start_time) * 1000
        else:
            duration_ms = None

        # Retrieve tool_arguments from start_info for key parity with tool.start
        tool_arguments = start_info.get("tool_arguments") if start_info else None

        # Build metadata with call_id and orphaned flag
        metadata = {"call_id": call_id} if call_id else {}
        if orphaned:
            metadata["orphaned"] = True

        event = AgentEvent(
            event_type=EventType.TOOL_END,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            tool_name=tool_name,
            tool_arguments=tool_arguments,  # Include for key parity with tool.start
            tool_result=result,
            duration_ms=duration_ms,
            parent_event_id=start_info.get("event_id") if start_info else None,
            metadata=metadata,
        )

        await self.emit(event)

    # ============================================
    # Delegation Events
    # ============================================

    async def emit_delegation_start(
        self,
        from_agent: AgentRole,
        to_agent: AgentRole,
        task: str,
        delegation_id: Optional[str] = None
    ) -> str:
        """
        Emit delegation start event.

        Args:
            from_agent: Agent delegating the task
            to_agent: Agent receiving the task
            task: Task description
            delegation_id: OpenAI's call_id for delegate_task_to_member, used for correlating start/end

        Returns:
            Event ID (correlation ID for all delegation events)
        """
        event_id = str(uuid.uuid4())
        # Use delegation_id for key if available (supports parallel delegations to same agent)
        key = f"delegation_{delegation_id or f'{from_agent.value}_{to_agent.value}'}"

        self._start_times[key] = time.time()
        self._active_events[key] = {
            "event_id": event_id,
            "start_time": self._start_times[key],
            "correlation_id": event_id,
            "delegation_id": delegation_id,
            "task": task  # Store task for emit_delegation_end to include in end event
        }

        event = AgentEvent(
            event_type=EventType.DELEGATION_START,
            event_id=event_id,
            agent_role=from_agent,
            agent_name=get_agent_name(from_agent),
            delegation_from=get_agent_name(from_agent),
            delegation_to=get_agent_name(to_agent),
            delegation_task=task,
            correlation_id=event_id,
            metadata={"delegation_id": delegation_id} if delegation_id else {},
        )

        await self.emit(event)
        return event_id

    async def emit_delegation_end(
        self,
        from_agent: AgentRole,
        to_agent: AgentRole,
        delegation_id: Optional[str] = None
    ):
        """
        Emit delegation end event.

        Args:
            from_agent: Agent who delegated
            to_agent: Agent who completed the task
            delegation_id: OpenAI's call_id for delegate_task_to_member, used for correlating start/end
        """
        # Use delegation_id for key if available (supports parallel delegations to same agent)
        key = f"delegation_{delegation_id or f'{from_agent.value}_{to_agent.value}'}"
        start_info = self._active_events.pop(key, None)
        start_time = self._start_times.pop(key, None)

        # Use stored delegation_id if not provided
        delegation_id = delegation_id or (start_info.get("delegation_id") if start_info else None)

        duration_ms = None
        if start_time is not None:
            duration_ms = (time.time() - start_time) * 1000

        # Retrieve task from start_info for key parity with delegation.start
        task = start_info.get("task", "") if start_info else ""

        event = AgentEvent(
            event_type=EventType.DELEGATION_END,
            event_id=str(uuid.uuid4()),
            agent_role=from_agent,
            agent_name=get_agent_name(from_agent),
            delegation_from=get_agent_name(from_agent),
            delegation_to=get_agent_name(to_agent),
            delegation_task=task,  # Include task for key parity with delegation.start
            duration_ms=duration_ms,
            parent_event_id=start_info.get("event_id") if start_info else None,
            correlation_id=start_info.get("correlation_id") if start_info else None,
            metadata={"delegation_id": delegation_id} if delegation_id else {},
        )

        await self.emit(event)

    # ============================================
    # Response Events
    # ============================================

    async def emit_response_start(self, agent_role: AgentRole, response_id: Optional[str] = None) -> str:
        """
        Emit response start event (final answer).

        Args:
            agent_role: Which agent is responding
            response_id: OpenAI's item_id (msg_XXX format) for correlating start/delta/end events

        Returns:
            Event ID
        """
        event_id = str(uuid.uuid4())
        # Use response_id for key if available (supports parallel responses from same agent)
        key = f"response_{response_id or agent_role.value}"

        self._start_times[key] = time.time()
        self._active_events[key] = {
            "event_id": event_id,
            "start_time": self._start_times[key],
            "response_id": response_id
        }

        event = AgentEvent(
            event_type=EventType.RESPONSE_START,
            event_id=event_id,
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            metadata={"response_id": response_id} if response_id else {},
        )

        await self.emit(event)
        return event_id

    async def emit_response_delta(self, agent_role: AgentRole, content: str, response_id: Optional[str] = None):
        """
        Emit response delta event (streaming final answer).

        Args:
            agent_role: Which agent is responding
            content: Response text chunk
            response_id: OpenAI's item_id (msg_XXX format) for correlating start/delta/end events
        """
        key = f"response_{response_id or agent_role.value}"
        active_event = self._active_events.get(key, {})
        parent_id = active_event.get("event_id")
        # Use stored response_id if not provided
        response_id = response_id or active_event.get("response_id")

        event = AgentEvent(
            event_type=EventType.RESPONSE_DELTA,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            content=content,
            parent_event_id=parent_id,
            metadata={"response_id": response_id} if response_id else {},
        )

        await self.emit(event)

    async def emit_response_end(
        self,
        agent_role: AgentRole,
        is_final_response: bool = False,
        response_id: Optional[str] = None
    ):
        """
        Emit response end event.

        Args:
            agent_role: Which agent finished responding
            is_final_response: True if this is the final response to show in the
                               dedicated "Final Response" box. Determined by:
                               - respond_directly=True → specialist's response is final
                               - respond_directly=False → Router's synthesis is final
            response_id: OpenAI's item_id (msg_XXX format) for correlating start/delta/end events
        """
        key = f"response_{response_id or agent_role.value}"
        start_info = self._active_events.pop(key, None)
        start_time = self._start_times.pop(key, None)

        # Use stored response_id if not provided
        response_id = response_id or (start_info.get("response_id") if start_info else None)

        duration_ms = None
        if start_time is not None:
            duration_ms = (time.time() - start_time) * 1000

        # Build metadata with is_final_response flag and response_id
        metadata = {}
        if is_final_response:
            metadata["is_final_response"] = True
        if response_id:
            metadata["response_id"] = response_id

        event = AgentEvent(
            event_type=EventType.RESPONSE_END,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            duration_ms=duration_ms,
            parent_event_id=start_info.get("event_id") if start_info else None,
            metadata=metadata if metadata else {}
        )

        await self.emit(event)

    # ============================================
    # Error Events
    # ============================================

    async def emit_error(
        self,
        agent_role: AgentRole,
        error_message: str,
        error_type: Optional[str] = None,
        error_traceback: Optional[str] = None
    ):
        """
        Emit error event.

        Args:
            agent_role: Which agent encountered the error
            error_message: Error message
            error_type: Exception type
            error_traceback: Full traceback
        """
        event = AgentEvent(
            event_type=EventType.ERROR,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            error_message=error_message,
            error_type=error_type,
            error_traceback=error_traceback
        )

        await self.emit(event)

    # ============================================
    # Citation Events
    # ============================================

    async def emit_citation_index(
        self,
        agent_role: AgentRole,
        citation_index: Dict[int, Any]
    ):
        """
        Emit citation index event.

        Args:
            agent_role: Which agent is emitting the citations
            citation_index: Dictionary mapping citation numbers to metadata
        """
        event = AgentEvent(
            event_type=EventType.CITATION_INDEX,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            metadata={"citation_index": citation_index}  # Store in metadata since AgentEvent doesn't have citation_index field
        )

        await self.emit(event)

    # ============================================
    # Graph Display Events
    # ============================================

    async def emit_graph_display(
        self,
        agent_role: AgentRole,
        source_id: str,
        graph_id: str,
        name: str,
        graph_category: str,
        company_id: Optional[str],
        fund_id: Optional[str],
        tool_name: str,
        fund_graph_selection: Optional[str] = None
    ):
        """
        Emit graph display event when [_graph_XXX] is detected.

        Uses MCP contract field names (2025-12-08):
        - name: Graph name (not graph_name)
        - graph_category: "Company" or "Fund" (Title Case, not entity_type)
        - company_id/fund_id: Separate fields (not entity_id)

        Args:
            agent_role: Which agent is emitting the graph
            source_id: Full source ID (e.g., "_src_6Hr")
            graph_id: Full graph ID (e.g., "_graph_6Hr")
            name: Name of the graph (e.g., "runway", "cac_payback")
            graph_category: Category - "Company" or "Fund" (Title Case)
            company_id: Company ID or None
            fund_id: Fund ID or None
            tool_name: Name of the tool that produced this data
            fund_graph_selection: Fund filter - "active", "exit", or "both"
        """
        event = AgentEvent(
            event_type=EventType.GRAPH_DISPLAY,
            event_id=str(uuid.uuid4()),
            agent_role=agent_role,
            agent_name=get_agent_name(agent_role),
            metadata={
                "source_id": source_id,
                "graph_id": graph_id,
                "type": "dataset",
                "name": name,
                "graph_category": graph_category,
                "company_id": company_id,
                "fund_id": fund_id,
                "tool_name": tool_name,
                "fund_graph_selection": fund_graph_selection
            }
        )

        await self.emit(event)
        logger.debug(f"[EventManager] Emitted graph.display: {graph_id} ({name})")

    # ============================================
    # Cleanup
    # ============================================

    def clear(self):
        """Clear all active events and timings (e.g., at start of new query)"""
        self._active_events.clear()
        self._start_times.clear()
