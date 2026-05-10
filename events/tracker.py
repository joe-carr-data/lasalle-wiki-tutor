"""
Agent Context Tracker - Tracks which agent is currently active

This module provides:
- AgentContextTracker: Stack-based tracker for sequential delegation
- ParallelAgentTracker: Map-based tracker for parallel delegation (V2)

The V2 tracker handles parallel execution where multiple agents can be
active simultaneously, using run_id and agent_name for attribution.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set
from .models import AgentRole, parse_member_id_to_role
from utils.logger import logger


# ═══════════════════════════════════════════════════════════════════════════
# V2: Parallel Agent Tracker
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ActiveAgentRun:
    """Represents an active agent run for parallel tracking."""
    agent_role: AgentRole
    agent_name: str
    run_id: str
    start_time: float = field(default_factory=time.time)
    tools_executed: List[str] = field(default_factory=list)
    is_complete: bool = False


class ParallelAgentTracker:
    """
    V2 Tracker for parallel agent execution.

    Unlike the stack-based AgentContextTracker, this tracker:
    - Uses run_id to track agents (not stack position)
    - Can handle multiple active agents simultaneously
    - Uses event metadata (agent_name) as the primary source of truth
    - Falls back to tool-based attribution when agent_name is unavailable

    Usage:
        tracker = ParallelAgentTracker()

        # When agent run starts (from AgentRunStartedEvent)
        tracker.register_agent_start("underwriting-agent", run_id="abc123")

        # Get agent for attribution
        agent = tracker.get_agent_for_event(event)  # Uses agent_name if available

        # When agent run completes
        tracker.register_agent_complete("underwriting-agent")

        # Check parallel mode
        if tracker.is_parallel:
            # Multiple agents active
            pass
    """

    # Tool -> Agent mapping for fallback attribution
    TOOL_TO_AGENT: Dict[str, AgentRole] = {
        # Router tools
        "recognize_entities": AgentRole.ROUTER,
        "delegate_task_to_member": AgentRole.ROUTER,

        # Underwriting tools (MCP - financial/credit analysis)
        "company_info": AgentRole.UNDERWRITING,
        "credit_score": AgentRole.UNDERWRITING,
        "get_credit_score": AgentRole.UNDERWRITING,
        "get_company_info": AgentRole.UNDERWRITING,
        "get_financials": AgentRole.UNDERWRITING,
        "get_runway_data": AgentRole.UNDERWRITING,
        "get_revenue_data": AgentRole.UNDERWRITING,
        "get_magic_number_data": AgentRole.UNDERWRITING,
        "get_cac_payback_data": AgentRole.UNDERWRITING,
        "get_burn_rate_data": AgentRole.UNDERWRITING,
        "scores": AgentRole.UNDERWRITING,

        # Origination tools (PostgreSQL - relationship/deal analysis)
        "get_ceo_contact": AgentRole.ORIGINATION,
        "get_relationship": AgentRole.ORIGINATION,
        "search_origination": AgentRole.ORIGINATION,
        "get_deal_info": AgentRole.ORIGINATION,
        "get_company_contacts": AgentRole.ORIGINATION,

        # PostgreSQL generic tools (legacy, kept for backward compat)
        "run_query": AgentRole.ORIGINATION,
        "show_tables": AgentRole.ORIGINATION,
        "describe_table": AgentRole.ORIGINATION,
        "list_schemas": AgentRole.ORIGINATION,

        # Hint pipeline + async SQL tools (used by Origination Agent with hints)
        "get_query_hint": AgentRole.ORIGINATION,
        "execute_sql": AgentRole.ORIGINATION,
    }

    def __init__(self):
        """Initialize the parallel agent tracker."""
        # Active agents by role
        self._active_agents: Dict[AgentRole, ActiveAgentRun] = {}

        # Agent name -> role mapping (for quick lookups)
        self._name_to_role: Dict[str, AgentRole] = {
            "Router Agent": AgentRole.ROUTER,
            "Underwriting Agent": AgentRole.UNDERWRITING,
            "Origination Agent": AgentRole.ORIGINATION,
        }

        # Run ID -> agent role mapping
        self._run_to_agent: Dict[str, AgentRole] = {}

        # Track pending tool calls (tool_call_id -> agent_role)
        # Used to attribute tool_end events correctly
        self._pending_tools: Dict[str, AgentRole] = {}

        # Delegation tracking for respond_directly=False
        self._active_delegations: List[Dict] = []

        # Last specialist agent (for final response attribution)
        self._last_specialist: Optional[AgentRole] = None

        # V2.1 FIX: Track current OpenAI event context
        # This tracks which agent's OpenAI response we're currently receiving.
        # When AgentRunStartedEvent("Underwriting Agent") arrives, all subsequent
        # OpenAI events (reasoning, etc.) belong to that agent until completion.
        # This fixes the bug where reasoning events were attributed to ROUTER
        # when multiple specialists were active in parallel.
        self._current_openai_context: Optional[AgentRole] = None

        logger.debug("[ParallelAgentTracker] Initialized")

    def reset(self):
        """Reset all state (call at start of new query)."""
        self._active_agents.clear()
        self._run_to_agent.clear()
        self._pending_tools.clear()
        self._active_delegations.clear()
        self._last_specialist = None
        self._current_openai_context = None
        logger.debug("[ParallelAgentTracker] Reset all state")

    # ═══════════════════════════════════════════════════════════════════════
    # Agent Run Lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def register_agent_start(
        self,
        agent_name: str,
        run_id: str = "",
        member_id: str = ""
    ) -> AgentRole:
        """
        Register when an agent run starts (from AgentRunStartedEvent).

        Args:
            agent_name: Agent name from event (e.g., "Underwriting Agent")
            run_id: Unique run ID from Agno
            member_id: Member ID if available (e.g., "underwriting-agent")

        Returns:
            The agent role that was registered
        """
        # Determine agent role
        role = self._name_to_role.get(agent_name)
        if not role and member_id:
            role = parse_member_id_to_role(member_id)
        if not role:
            role = AgentRole.ROUTER
            logger.warning(f"[ParallelAgentTracker] Unknown agent '{agent_name}', defaulting to ROUTER")

        # Track specialist
        if role != AgentRole.ROUTER:
            self._last_specialist = role

        # V2.1 FIX: Set current OpenAI context
        # All subsequent OpenAI events (reasoning, etc.) belong to this agent
        # until we see AgentRunCompletedEvent for this agent or another agent starts.
        # This is the key fix for reasoning attribution in parallel execution.
        self._current_openai_context = role
        logger.debug(f"[ParallelAgentTracker] Set OpenAI context to {role.value}")

        # Create active run entry
        run = ActiveAgentRun(
            agent_role=role,
            agent_name=agent_name,
            run_id=run_id or f"run_{role.value}_{time.time()}"
        )
        self._active_agents[role] = run
        if run_id:
            self._run_to_agent[run_id] = role

        logger.info(
            f"[ParallelAgentTracker] Agent started: {role.value} "
            f"(run_id={run_id[:8] if run_id else 'N/A'}..., "
            f"active={list(self._active_agents.keys())}, openai_context={self._current_openai_context.value})"
        )

        return role

    def register_agent_complete(self, agent_name: str, run_id: str = "") -> Optional[AgentRole]:
        """
        Register when an agent run completes (from AgentRunCompletedEvent).

        Args:
            agent_name: Agent name from event
            run_id: Run ID if available

        Returns:
            The agent role that completed, or None
        """
        role = self._name_to_role.get(agent_name)
        if not role and run_id:
            role = self._run_to_agent.get(run_id)

        if role and role in self._active_agents:
            self._active_agents[role].is_complete = True
            del self._active_agents[role]
            if run_id and run_id in self._run_to_agent:
                del self._run_to_agent[run_id]

            # V2.1 FIX: Clear OpenAI context if the completing agent matches
            # This allows the next agent's events to be attributed correctly
            if self._current_openai_context == role:
                self._current_openai_context = None
                logger.debug(f"[ParallelAgentTracker] Cleared OpenAI context (was {role.value})")

            logger.info(
                f"[ParallelAgentTracker] Agent completed: {role.value} "
                f"(remaining={list(self._active_agents.keys())}, openai_context={self._current_openai_context.value if self._current_openai_context else 'None'})"
            )
            return role

        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Tool Tracking
    # ═══════════════════════════════════════════════════════════════════════

    def register_tool_start(self, tool_name: str, call_id: str, agent_role: AgentRole):
        """Register tool start for later attribution of tool_end."""
        self._pending_tools[call_id] = agent_role
        if agent_role in self._active_agents:
            self._active_agents[agent_role].tools_executed.append(tool_name)

    def get_agent_for_tool_end(self, call_id: str) -> Optional[AgentRole]:
        """Get agent for tool_end event based on call_id."""
        return self._pending_tools.pop(call_id, None)

    # ═══════════════════════════════════════════════════════════════════════
    # Delegation Tracking
    # ═══════════════════════════════════════════════════════════════════════

    def register_delegation_start(self, from_agent: AgentRole, to_agent: AgentRole, task: str):
        """Register delegation start."""
        self._active_delegations.append({
            "from_agent": from_agent,
            "to_agent": to_agent,
            "task": task,
            "start_time": time.time()
        })

    def register_delegation_end(self, to_agent: AgentRole) -> Optional[Dict]:
        """Register delegation end, returns the delegation info if found."""
        for i, d in enumerate(self._active_delegations):
            if d["to_agent"] == to_agent:
                return self._active_delegations.pop(i)
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Agent Attribution (THE KEY FIX)
    # ═══════════════════════════════════════════════════════════════════════

    def get_agent_for_event(self, event, default: AgentRole = AgentRole.ROUTER) -> AgentRole:
        """
        Get agent role for an event using multiple attribution strategies.

        Priority:
        1. event.agent_name (if present and valid) - MOST RELIABLE
        2. event.run_id mapping (if tracked)
        3. Tool-based attribution (for tool events)
        4. If only one specialist is active, use that
        5. Current OpenAI context (V2.1 FIX for reasoning events)
        6. Default (usually ROUTER)

        This is THE key fix for parallel execution - we trust the event's
        own metadata rather than a stack-based tracker.

        V2.1 FIX: Added Strategy 5 to use _current_openai_context for events
        that lack agent_name (like OpenAI reasoning events). This fixes the bug
        where reasoning from Underwriting was attributed to Router during
        parallel execution.

        Args:
            event: The event to attribute
            default: Default agent if no attribution found

        Returns:
            AgentRole for the event
        """
        # Strategy 1: Use agent_name from event (most reliable)
        agent_name = getattr(event, 'agent_name', None)
        if agent_name:
            role = self._name_to_role.get(agent_name)
            if role:
                return role

        # Strategy 2: Use run_id mapping
        run_id = getattr(event, 'run_id', None)
        if run_id and run_id in self._run_to_agent:
            return self._run_to_agent[run_id]

        # Strategy 3: Tool-based attribution
        tool_name = getattr(event, 'tool_name', None) or getattr(event, 'name', None)
        if tool_name and tool_name in self.TOOL_TO_AGENT:
            return self.TOOL_TO_AGENT[tool_name]

        # Strategy 4: If only one specialist is active, use that
        specialists = [r for r in self._active_agents.keys() if r != AgentRole.ROUTER]
        if len(specialists) == 1:
            return specialists[0]

        # Strategy 5 (V2.1 FIX): Use current OpenAI context
        # This is set when AgentRunStartedEvent arrives, so we know which agent's
        # response we're currently streaming. This fixes reasoning attribution
        # when multiple specialists are active (Strategy 4 fails).
        if self._current_openai_context:
            logger.debug(
                f"[ParallelAgentTracker] Using OpenAI context for attribution: "
                f"{self._current_openai_context.value} (event type: {getattr(event, 'type', 'unknown')})"
            )
            return self._current_openai_context

        # Fallback to default
        return default

    def get_agent_for_tool(self, tool_name: str) -> AgentRole:
        """
        Get agent for a tool call based on current execution context.

        Attribution priority:
        1. If only ONE specialist agent is active → use that agent
           (This is the most reliable - we know which agent is running)
        2. If multiple specialists active (true parallel) → use TOOL_TO_AGENT mapping as hint
        3. Fallback to Router

        NOTE: We prefer active agent context over static mapping because:
        - Different agents CAN share the same MCP tools
        - The mapping is fragile and requires manual maintenance
        - Active agent context is dynamic and always accurate

        Args:
            tool_name: Name of the tool being called

        Returns:
            AgentRole of the agent making this tool call
        """
        # Strategy 1: If only one specialist is active, use that (MOST RELIABLE)
        specialists = [r for r in self._active_agents.keys() if r != AgentRole.ROUTER]
        if len(specialists) == 1:
            logger.debug(f"[get_agent_for_tool] {tool_name} → {specialists[0].value} (single active specialist)")
            return specialists[0]

        # Strategy 2: Multiple specialists active - use tool mapping as a HINT
        # This is only for parallel execution where we can't determine from context alone
        if tool_name in self.TOOL_TO_AGENT:
            agent = self.TOOL_TO_AGENT[tool_name]
            # Only use if that agent is actually active
            if agent in self._active_agents:
                logger.debug(f"[get_agent_for_tool] {tool_name} → {agent.value} (tool mapping, agent active)")
                return agent

        # Strategy 3: Use last active specialist if available
        if self._last_specialist and self._last_specialist in self._active_agents:
            logger.debug(f"[get_agent_for_tool] {tool_name} → {self._last_specialist.value} (last specialist)")
            return self._last_specialist

        # Fallback to Router
        logger.debug(f"[get_agent_for_tool] {tool_name} → router (fallback)")
        return AgentRole.ROUTER

    def get_agent_for_response(self, event, respond_directly: bool) -> AgentRole:
        """
        Get agent for response content attribution.

        For respond_directly=False:
        - Specialist responses go to the specialist
        - Router synthesis (no agent_name) goes to Router

        For respond_directly=True:
        - All responses go to the source agent

        Args:
            event: The response event
            respond_directly: Team's respond_directly setting

        Returns:
            AgentRole for response attribution
        """
        # Check for explicit agent_name
        agent_name = getattr(event, 'agent_name', None)
        if agent_name:
            role = self._name_to_role.get(agent_name)
            if role:
                return role

        # For respond_directly=False, content without agent_name is Router synthesis
        if not respond_directly:
            return AgentRole.ROUTER

        # Fallback to last active specialist or Router
        if self._last_specialist and self._last_specialist in self._active_agents:
            return self._last_specialist

        return AgentRole.ROUTER

    # ═══════════════════════════════════════════════════════════════════════
    # State Queries
    # ═══════════════════════════════════════════════════════════════════════

    @property
    def is_parallel(self) -> bool:
        """Check if multiple agents are active (parallel execution)."""
        # Count non-router active agents
        specialists = [r for r in self._active_agents.keys() if r != AgentRole.ROUTER]
        return len(specialists) > 1

    @property
    def active_agents(self) -> List[AgentRole]:
        """Get list of currently active agents."""
        return list(self._active_agents.keys())

    @property
    def active_specialists(self) -> List[AgentRole]:
        """Get list of active specialist agents (non-router)."""
        return [r for r in self._active_agents.keys() if r != AgentRole.ROUTER]

    @property
    def last_specialist(self) -> Optional[AgentRole]:
        """Get the last specialist that was delegated to."""
        return self._last_specialist

    @property
    def has_active_delegations(self) -> bool:
        """Check if there are active delegations."""
        return len(self._active_delegations) > 0

    @property
    def current_openai_context(self) -> Optional[AgentRole]:
        """
        Get the current OpenAI event context (V2.1 FIX).

        This tracks which agent's OpenAI response we're currently receiving.
        Used for attributing reasoning events that lack agent_name metadata.
        """
        return self._current_openai_context

    def get_active_delegation_count(self) -> int:
        """Get count of active delegations."""
        return len(self._active_delegations)

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ParallelAgentTracker("
            f"active={[r.value for r in self._active_agents.keys()]}, "
            f"parallel={self.is_parallel}, "
            f"last_specialist={self._last_specialist.value if self._last_specialist else None}, "
            f"openai_context={self._current_openai_context.value if self._current_openai_context else None}"
            f")"
        )


class AgentContextTracker:
    """
    Tracks which agent is currently active in the multi-agent system.

    The tracker maintains a stack of active agents. When the Router agent
    delegates to the Underwriting agent, we push Underwriting onto the stack.
    When delegation completes, we pop back to Router.

    This ensures all events are properly attributed to the correct agent.

    Example:
        >>> tracker = AgentContextTracker()
        >>> tracker.current_agent
        AgentRole.ROUTER

        >>> tracker.push_agent("underwriting-agent")
        >>> tracker.current_agent
        AgentRole.UNDERWRITING

        >>> tracker.pop_agent()
        >>> tracker.current_agent
        AgentRole.ROUTER
    """

    def __init__(self, initial_agent: AgentRole = AgentRole.ROUTER):
        """
        Initialize the tracker.

        Args:
            initial_agent: Starting agent (default: ROUTER)
        """
        # Agent stack (bottom = root, top = current)
        self._agent_stack: List[AgentRole] = [initial_agent]

        # Delegation chain tracking
        self._delegation_chain: List[str] = []

        logger.info(f"[AgentContextTracker] Initialized with agent: {initial_agent.value}")

    # ============================================
    # Stack Management
    # ============================================

    def push_agent(self, member_id: str):
        """
        Push new agent onto stack (when delegating).

        Args:
            member_id: Agno member ID (e.g., 'underwriting-agent')

        Example:
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.current_agent
            AgentRole.UNDERWRITING
        """
        agent_role = parse_member_id_to_role(member_id)
        self._agent_stack.append(agent_role)
        self._delegation_chain.append(f"{self.parent_agent.value if self.parent_agent else 'root'} → {agent_role.value}")

        logger.info(f"[AgentContextTracker] Pushed agent: {agent_role.value} (stack size: {len(self._agent_stack)})")

    def pop_agent(self) -> Optional[AgentRole]:
        """
        Pop agent from stack (when delegation completes).

        Returns:
            The agent that was popped, or None if stack has only root

        Example:
            >>> tracker.pop_agent()
            AgentRole.UNDERWRITING
            >>> tracker.current_agent
            AgentRole.ROUTER
        """
        if len(self._agent_stack) > 1:
            popped = self._agent_stack.pop()
            if self._delegation_chain:
                self._delegation_chain.pop()
            logger.info(f"[AgentContextTracker] Popped agent: {popped.value} (stack size: {len(self._agent_stack)})")
            return popped
        else:
            logger.warning("[AgentContextTracker] Cannot pop root agent")
            return None

    def reset(self, agent: AgentRole = AgentRole.ROUTER):
        """
        Reset stack to single agent (e.g., at start of new query).

        Args:
            agent: Agent to reset to (default: ROUTER)
        """
        self._agent_stack = [agent]
        self._delegation_chain = []
        logger.info(f"[AgentContextTracker] Reset to agent: {agent.value}")

    # ============================================
    # Current State Queries
    # ============================================

    @property
    def current_agent(self) -> AgentRole:
        """
        Get current active agent (top of stack).

        Returns:
            Current agent role

        Example:
            >>> tracker.current_agent
            AgentRole.ROUTER
        """
        return self._agent_stack[-1]

    @property
    def parent_agent(self) -> Optional[AgentRole]:
        """
        Get parent agent (who delegated to current agent).

        Returns:
            Parent agent role, or None if at root

        Example:
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.parent_agent
            AgentRole.ROUTER
        """
        return self._agent_stack[-2] if len(self._agent_stack) > 1 else None

    @property
    def is_delegated(self) -> bool:
        """
        Check if currently in a delegation (not at root).

        Returns:
            True if delegated, False if at root

        Example:
            >>> tracker.is_delegated
            False
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.is_delegated
            True
        """
        return len(self._agent_stack) > 1

    @property
    def depth(self) -> int:
        """
        Get current delegation depth.

        Returns:
            Depth (0 = root, 1 = one level of delegation, etc.)

        Example:
            >>> tracker.depth
            0
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.depth
            1
        """
        return len(self._agent_stack) - 1

    @property
    def root_agent(self) -> AgentRole:
        """
        Get root agent (bottom of stack).

        Returns:
            Root agent role

        Example:
            >>> tracker.root_agent
            AgentRole.ROUTER
        """
        return self._agent_stack[0]

    # ============================================
    # Delegation Chain
    # ============================================

    def get_delegation_chain(self) -> List[str]:
        """
        Get full delegation chain as human-readable strings.

        Returns:
            List of delegation strings (e.g., ["router → underwriting"])

        Example:
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.get_delegation_chain()
            ['router → underwriting']
        """
        return self._delegation_chain.copy()

    def get_full_path(self) -> str:
        """
        Get full agent path as string.

        Returns:
            Agent path (e.g., "Router → Underwriting → Origination")

        Example:
            >>> tracker.push_agent("underwriting-agent")
            >>> tracker.get_full_path()
            'router → underwriting'
        """
        return " → ".join(agent.value for agent in self._agent_stack)

    # ============================================
    # Context Helpers
    # ============================================

    def should_attribute_to_current(self, event_source: Optional[str] = None) -> bool:
        """
        Determine if event should be attributed to current agent.

        This is useful when events don't have clear agent information.

        Args:
            event_source: Optional source hint

        Returns:
            True if event should be attributed to current agent

        Example:
            >>> tracker.should_attribute_to_current()
            True
        """
        # By default, attribute to current agent
        # Can be extended with more sophisticated logic if needed
        return True

    def get_agent_for_tool(self, tool_name: str) -> AgentRole:
        """
        Get agent responsible for a tool call.

        Some tools are specific to certain agents (e.g., recognize_entities
        is always called by Router).

        Args:
            tool_name: Name of the tool

        Returns:
            Agent role responsible for this tool

        Example:
            >>> tracker.get_agent_for_tool("recognize_entities")
            AgentRole.ROUTER
        """
        # Tool -> Agent mapping
        router_tools = {
            "recognize_entities",
            "delegate_task_to_member"
        }

        underwriting_tools = {
            "company_info",
            "credit_score",
            "scores",
            "get_magic_number_data",
            "get_revenue_data"
        }

        # Check if tool is specific to an agent
        if tool_name in router_tools:
            return AgentRole.ROUTER
        elif tool_name in underwriting_tools:
            return AgentRole.UNDERWRITING
        else:
            # Default to current agent
            return self.current_agent

    # ============================================
    # Debug / Logging
    # ============================================

    def __repr__(self) -> str:
        """String representation for debugging"""
        return f"AgentContextTracker(current={self.current_agent.value}, depth={self.depth}, path={self.get_full_path()})"

    def log_state(self):
        """Log current tracker state for debugging"""
        logger.info(f"[AgentContextTracker] State: {repr(self)}")
        if self._delegation_chain:
            logger.info(f"[AgentContextTracker] Delegation chain: {self._delegation_chain}")
