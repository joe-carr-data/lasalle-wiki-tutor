"""
Event Models - Unified event system for agent activities

This module defines the core event models used throughout the LQC Data Intelligence Team.
All events are Pydantic models for type safety and easy serialization.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid


class AgentRole(str, Enum):
    """Agent roles in the multi-agent system.

    The first four values are inherited from the original repo (lqc-ai-assistant-lib)
    and kept for compatibility with the ported tracker / smart_renderer logic.
    `ASSISTANT` is the generic single-agent role used by the LaSalle catalog skeleton.
    """
    ROUTER = "router"
    UNDERWRITING = "underwriting"
    ORIGINATION = "origination"
    TEXT2SQL = "text2sql"
    ASSISTANT = "assistant"


class ParallelContext(BaseModel):
    """
    Context for parallel agent execution.

    When multiple agents run simultaneously, this provides
    information about the parallel execution group.
    """
    is_parallel: bool = Field(
        default=False,
        description="Whether this event is part of parallel execution"
    )
    parallel_group_id: str = Field(
        default="",
        description="Unique ID grouping all parallel agents in this delegation"
    )
    agent_index: int = Field(
        default=0,
        description="Index of this agent in the parallel group (0-based)"
    )
    total_parallel_agents: int = Field(
        default=1,
        description="Total number of agents in the parallel group"
    )


class EventType(str, Enum):
    """All possible event types in the system"""

    # Reasoning events (model thinking)
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"

    # Function arguments events (before tool execution)
    ARGUMENTS_START = "arguments_start"
    ARGUMENTS_DELTA = "arguments_delta"
    ARGUMENTS_END = "arguments_end"

    # Tool execution events
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"

    # Delegation events (agent → agent)
    DELEGATION_START = "delegation_start"
    DELEGATION_END = "delegation_end"

    # Final response events
    RESPONSE_START = "response_start"
    RESPONSE_DELTA = "response_delta"
    RESPONSE_END = "response_end"

    # Citation events (source tracking)
    CITATION_INDEX = "citation_index"

    # Graph display events (for [_graph_XXX] citations)
    GRAPH_DISPLAY = "graph_display"

    # Error events
    ERROR = "error"

    # Cancellation events
    CANCELLED = "cancelled"


class AgentEvent(BaseModel):
    """
    Unified event model for all agent activities.

    This model represents any event that can occur in the system, with complete
    authorship tracking and metadata for backend consumption.

    Examples:
        # Reasoning event
        event = AgentEvent(
            event_type=EventType.REASONING_START,
            agent_role=AgentRole.ROUTER,
            agent_name="Router Agent"
        )

        # Tool execution event
        event = AgentEvent(
            event_type=EventType.TOOL_START,
            agent_role=AgentRole.UNDERWRITING,
            agent_name="Underwriting Agent",
            tool_name="company_info",
            tool_arguments={"company_id": "3980"}
        )

        # Delegation event
        event = AgentEvent(
            event_type=EventType.DELEGATION_START,
            agent_role=AgentRole.ROUTER,
            agent_name="Router Agent",
            delegation_from="Router Agent",
            delegation_to="Underwriting Agent",
            delegation_task="Get credit score for Avaamo"
        )
    """

    # ============================================
    # Event Identification
    # ============================================
    event_type: EventType = Field(
        description="Type of event"
    )

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique event ID (UUID)"
    )

    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the event was created"
    )

    # ============================================
    # Agent Authorship (WHO)
    # ============================================
    agent_role: AgentRole = Field(
        description="Role of the agent generating this event"
    )

    agent_name: str = Field(
        description="Human-readable agent name (e.g., 'Router Agent')"
    )

    # ============================================
    # Event Content (WHAT)
    # ============================================
    content: Optional[str] = Field(
        None,
        description="Text content (for delta events)"
    )

    # ============================================
    # Event Metadata
    # ============================================
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (extensible)"
    )

    # ============================================
    # Event Relationships
    # ============================================
    parent_event_id: Optional[str] = Field(
        None,
        description="Parent event ID for start/end pairing"
    )

    correlation_id: Optional[str] = Field(
        None,
        description="Groups related events (e.g., all events in a delegation)"
    )

    # ============================================
    # Session & Sequencing (NEW - for event sourcing)
    # ============================================
    sequence_number: int = Field(
        default=0,
        description="Global monotonic sequence for total ordering"
    )

    session_id: str = Field(
        default="",
        description="Session/conversation ID for grouping events"
    )

    agent_run_id: str = Field(
        default="",
        description="Unique run ID for this agent's execution"
    )

    # ============================================
    # Parallel Execution Context (NEW)
    # ============================================
    parallel_context: Optional[ParallelContext] = Field(
        None,
        description="Context for parallel agent execution"
    )

    # ============================================
    # Timing Information
    # ============================================
    duration_ms: Optional[float] = Field(
        None,
        description="Duration in milliseconds (for end events)"
    )

    # ============================================
    # Tool/Function Specific Fields
    # ============================================
    tool_name: Optional[str] = Field(
        None,
        description="Tool/function name being called"
    )

    tool_arguments: Optional[Dict[str, Any]] = Field(
        None,
        description="Parsed tool arguments"
    )

    tool_result: Optional[Any] = Field(
        None,
        description="Tool execution result (for tool_end events)"
    )

    # ============================================
    # Delegation Specific Fields
    # ============================================
    delegation_from: Optional[str] = Field(
        None,
        description="Source agent in delegation (human-readable)"
    )

    delegation_to: Optional[str] = Field(
        None,
        description="Target agent in delegation (human-readable)"
    )

    delegation_task: Optional[str] = Field(
        None,
        description="Task description for delegation"
    )

    # ============================================
    # Error Specific Fields
    # ============================================
    error_message: Optional[str] = Field(
        None,
        description="Error message (for error events)"
    )

    error_type: Optional[str] = Field(
        None,
        description="Error type/exception name"
    )

    error_traceback: Optional[str] = Field(
        None,
        description="Full error traceback"
    )

    class Config:
        """Pydantic configuration"""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump(mode='json', exclude_none=True)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return self.model_dump_json(exclude_none=True)


# ============================================
# Helper Functions
# ============================================

def get_agent_name(role: AgentRole) -> str:
    """
    Get human-readable agent name from role.

    Args:
        role: Agent role enum

    Returns:
        Human-readable name

    Examples:
        >>> get_agent_name(AgentRole.ROUTER)
        'Router Agent'
    """
    return {
        AgentRole.ROUTER: "Router Agent",
        AgentRole.UNDERWRITING: "Underwriting Agent",
        AgentRole.ORIGINATION: "Origination Agent",
        AgentRole.TEXT2SQL: "Text2SQL Agent",
        AgentRole.ASSISTANT: "LaSalle Wiki Tutor",
    }.get(role, "Unknown Agent")


def parse_member_id_to_role(member_id: str) -> AgentRole:
    """
    Parse member_id from Agno to agent role.

    Args:
        member_id: Agno member ID (e.g., 'underwriting-agent')

    Returns:
        Corresponding agent role

    Examples:
        >>> parse_member_id_to_role('underwriting-agent')
        AgentRole.UNDERWRITING
    """
    mapping = {
        "underwriting-agent": AgentRole.UNDERWRITING,
        "underwriting_agent": AgentRole.UNDERWRITING,
        "origination-agent": AgentRole.ORIGINATION,
        "origination_agent": AgentRole.ORIGINATION,
    }
    return mapping.get(member_id, AgentRole.ROUTER)
