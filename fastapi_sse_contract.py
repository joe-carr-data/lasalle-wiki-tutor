"""
SSE Event Contract for LQC Data Intelligence Team

Complete event schema for streaming agent operations over Server-Sent Events (SSE).
Designed for excellent frontend UX with minimal development time.

Event Stream Philosophy:
- Every event is self-contained (no need to correlate multiple events)
- Rich metadata for easy rendering
- Timing information on everything
- Agent context always included
- Progressive enhancement (events build on each other)
"""

from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
#                           EVENT TYPE TAXONOMY
# ═══════════════════════════════════════════════════════════════════════════

class SSEEventType(str, Enum):
    """
    Event types optimized for frontend rendering.

    Naming Convention: <category>.<action>[.<detail>]
    - session.* - Query lifecycle
    - agent.* - Agent operations
    - tool.* - Tool execution
    - delegation.* - Agent-to-agent handoff
    - response.* - Final answer streaming
    - error.* - Error conditions
    """

    # Session Events
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    # Classification Events (Auto mode query analysis)
    CLASSIFICATION_START = "classification.start"
    CLASSIFICATION_END = "classification.end"

    # Agent Thinking Events (Reasoning)
    AGENT_THINKING_START = "agent.thinking.start"
    AGENT_THINKING_DELTA = "agent.thinking.delta"  # Stream reasoning chunks
    AGENT_THINKING_END = "agent.thinking.end"

    # Tool Execution Events
    TOOL_START = "tool.start"
    TOOL_END = "tool.end"

    # Delegation Events (Agent → Agent)
    DELEGATION_START = "delegation.start"
    DELEGATION_END = "delegation.end"

    # Response Events (per-agent, for agent activity panel)
    RESPONSE_DELTA = "response.delta"  # Stream response chunks
    RESPONSE_END = "response.end"

    # Final Response Events (dedicated stream for final response box)
    # These fire IN ADDITION to response.* when is_final_response=True
    FINAL_RESPONSE_START = "final_response.start"    # Final response streaming begins
    FINAL_RESPONSE_DELTA = "final_response.delta"    # Chunks for final response box only
    FINAL_RESPONSE_END = "final_response.end"        # Final response complete

    # Citation Events
    CITATION_INDEX = "citation.index"

    # Final Response Event (for MongoDB persistence)
    RESPONSE_FINAL = "response.final"

    # Graph Display Events
    GRAPH_DISPLAY = "graph.display"

    # Report Events (Insert Question only)
    REPORT_ADDITIONAL_CONTENT = "report.additional_content"

    # Error Events
    ERROR = "error"

    # Cancellation Events
    CANCELLED = "cancelled"

    # CTA Events (Deal Agent specific)
    CTA = "cta"


# ═══════════════════════════════════════════════════════════════════════════
#                           AGENT METADATA
# ═══════════════════════════════════════════════════════════════════════════

class AgentRole(str, Enum):
    """Agent roles in the system"""
    ROUTER = "router"
    UNDERWRITING = "underwriting"
    ORIGINATION = "origination"
    TEXT2SQL = "text2sql"
    ASSISTANT = "assistant"


class AgentInfo(BaseModel):
    """
    Agent metadata for context.

    Frontend Use:
    - Display agent name with appropriate styling
    - Show agent icon based on role
    - Highlight active agent
    """
    role: AgentRole
    name: str  # e.g., "Router Agent", "Underwriting Agent"
    icon: str  # Emoji for display: "🔍", "📊", "💼"
    color: Optional[str] = None  # Hex color for styling: "#3B82F6"


# ═══════════════════════════════════════════════════════════════════════════
#                           TOOL METADATA
# ═══════════════════════════════════════════════════════════════════════════

class ToolInfo(BaseModel):
    """
    Tool metadata for display.

    Frontend Use:
    - Show tool name with icon
    - Display arguments in expandable section
    - Animate progress during execution
    - Show timing badge
    """
    name: str
    icon: str  # Emoji: "🔍", "🏢", "📊", "📈", "🔧"
    arguments: Dict[str, Any]
    arguments_display: str  # Compact string for inline display


# ═══════════════════════════════════════════════════════════════════════════
#                           BASE EVENT
# ═══════════════════════════════════════════════════════════════════════════

class SSEEvent(BaseModel):
    """
    Base SSE event structure.

    All events follow this schema for consistency.
    """
    event_id: str = Field(..., description="Unique event ID (UUID)")
    event_type: SSEEventType = Field(..., description="Event type")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    elapsed_ms: int = Field(..., description="Milliseconds since query started")

    # Correlation ID for matching start/end events
    # Frontend can use this unified field instead of event-specific IDs
    # (thinking_id, call_id, delegation_id, response_id, question_answer_id)
    correlation_id: Optional[str] = Field(None, description="Correlation ID for matching start/end events")

    # Agent context (which agent is active)
    agent: AgentInfo = Field(..., description="Current agent context")

    # Event-specific data
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific payload")

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "abc123-def456-...",
                "event_type": "tool.start",
                "timestamp": "2025-10-31T15:30:55.123Z",
                "elapsed_ms": 1234,
                "agent": {
                    "role": "router",
                    "name": "Router Agent",
                    "icon": "🔍",
                    "color": "#3B82F6"
                },
                "data": {
                    "tool": {
                        "name": "recognize_entities",
                        "icon": "🔍",
                        "arguments": {"entities": ["Avaamo"]},
                        "arguments_display": 'entities=["Avaamo"]'
                    }
                }
            }
        }


# ═══════════════════════════════════════════════════════════════════════════
#                           EVENT-SPECIFIC SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class SessionStartedEvent(SSEEvent):
    """
    Query session started.

    Frontend Action:
    - Show "Processing your query..." message
    - Start loading animation
    - Initialize timeline UI
    - Store question_answer_id for event persistence
    """
    event_type: SSEEventType = SSEEventType.SESSION_STARTED
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "query": "",
            "session_id": "",
            "question_answer_id": "",  # UUID for this Q&A exchange, available immediately
            "verbosity": 1
        }
    )


class ClassificationStartEvent(SSEEvent):
    """
    Auto-mode classification started.

    Emitted when reasoning_mode="auto" before the classifier runs.
    Allows frontend to show classification-in-progress UI.

    Frontend Action:
    - Show "Analyzing query complexity..." indicator
    - Display animated sparkles/brain icon
    - Prepare for classification result
    """
    event_type: SSEEventType = SSEEventType.CLASSIFICATION_START
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "query": "",  # The query being classified
            "message": "Analyzing query complexity..."
        }
    )


class ClassificationEndEvent(SSEEvent):
    """
    Auto-mode classification completed.

    Contains the classification result for frontend display.

    Frontend Action:
    - Show classification result with animation
    - Display resolved reasoning effort and agent approach
    - Transition to normal processing after brief display

    Note: Contains same keys as classification.start (plus results) for frontend consistency.
    """
    event_type: SSEEventType = SSEEventType.CLASSIFICATION_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "query": "",  # Same as classification.start - the query being classified
            "reasoning_mode": "auto",  # Original mode (always "auto" for this event)
            "resolved_reasoning_effort": "thinking",  # instant | thinking
            "agent_approach": "multi-agent",  # single-agent | multi-agent
            "reasoning": "",  # Brief explanation from classifier
            "duration_ms": 0  # How long classification took
        }
    )


class AgentThinkingStartEvent(SSEEvent):
    """
    Agent started reasoning.

    Frontend Action:
    - Show agent card with "thinking" indicator
    - Display pulsing/animated icon
    - Prepare to stream reasoning text
    - Store thinking_id for correlating with delta/end events
    """
    event_type: SSEEventType = SSEEventType.AGENT_THINKING_START
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "thinking_id": ""  # OpenAI's item_id (rs_XXX) for correlating start/delta/end events
        }
    )


class AgentThinkingDeltaEvent(SSEEvent):
    """
    Agent reasoning chunk (real-time streaming).

    Frontend Action:
    - Match with thinking.start using thinking_id
    - Append text chunk to reasoning display
    - Auto-scroll to latest content
    - Show typing indicator
    """
    event_type: SSEEventType = SSEEventType.AGENT_THINKING_DELTA
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "thinking_id": "",  # OpenAI's item_id (rs_XXX) for correlating start/delta/end events
            "delta": "",  # Text chunk to append
            "accumulated": ""  # Full text so far (optional, for recovery)
        }
    )


class AgentThinkingEndEvent(SSEEvent):
    """
    Agent finished reasoning.

    Frontend Action:
    - Match with thinking.start using thinking_id
    - Show duration badge
    - Stop thinking animation
    - Finalize reasoning display
    """
    event_type: SSEEventType = SSEEventType.AGENT_THINKING_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "thinking_id": "",  # OpenAI's item_id (rs_XXX) for correlating start/delta/end events
            "duration_ms": 0,
            "duration_display": "0.00s",
            "full_text": ""  # Complete reasoning text
        }
    )


class ToolStartEvent(SSEEvent):
    """
    Tool execution started.

    Frontend Action:
    - Show tool card with arguments
    - Start progress animation
    - Display "Executing..." status
    - Store call_id for correlating with tool.end
    """
    event_type: SSEEventType = SSEEventType.TOOL_START
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "tool": {
                "name": "",
                "call_id": "",  # OpenAI's call_id for correlating start/end events
                "icon": "🔧",
                "arguments": {},
                "arguments_display": ""
            }
        }
    )


class ToolEndEvent(SSEEvent):
    """
    Tool execution completed.

    Frontend Action:
    - Match with tool.start using call_id
    - Show success checkmark (or warning if orphaned)
    - Display duration badge
    - Show result preview (if available)
    - Stop progress animation
    - If orphaned=True, show warning indicator (tool didn't complete normally)
    """
    event_type: SSEEventType = SSEEventType.TOOL_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "tool": {
                "name": "",
                "call_id": "",  # OpenAI's call_id for correlating start/end events
                "icon": "🔧",
                "arguments": {},
                "arguments_display": ""
            },
            "duration_ms": 0,
            "duration_display": "0.00s",
            "result_preview": "",  # Optional: First 100 chars of result
            "success": True,
            "orphaned": False  # True if emitted via cleanup fallback (ToolCallCompletedEvent never arrived)
        }
    )


class DelegationStartEvent(SSEEvent):
    """
    Agent delegating to another agent.

    Frontend Action:
    - Show delegation animation (arrow from → to)
    - Display delegation task
    - Highlight target agent
    - Show handoff indicator
    - Store delegation_id for correlating with delegation.end
    """
    event_type: SSEEventType = SSEEventType.DELEGATION_START
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "delegation_id": "",  # OpenAI's call_id for delegate_task_to_member, correlates start/end
            "from_agent": {
                "role": "router",
                "name": "Router Agent",
                "icon": "🔍"
            },
            "to_agent": {
                "role": "underwriting",
                "name": "Underwriting Agent",
                "icon": "📊"
            },
            "task": "",  # Full delegation task description
            "task_preview": ""  # First 100 chars for compact display
        }
    )


class DelegationEndEvent(SSEEvent):
    """
    Delegation completed (specialist returned to router).

    Frontend Action:
    - Match with delegation.start using delegation_id
    - Show delegation completion
    - Display duration
    - Return focus to router agent

    Note: Contains same keys as delegation.start (plus duration) for frontend consistency.
    """
    event_type: SSEEventType = SSEEventType.DELEGATION_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "delegation_id": "",  # OpenAI's call_id for delegate_task_to_member, correlates start/end
            "from_agent": {
                "role": "router",
                "name": "Router Agent",
                "icon": "🔍"
            },
            "to_agent": {
                "role": "underwriting",
                "name": "Underwriting Agent",
                "icon": "📊"
            },
            "task": "",  # Same as delegation.start - full delegation task description
            "task_preview": "",  # Same as delegation.start - first 100 chars for compact display
            "duration_ms": 0,
            "duration_display": "0.00s"
        }
    )


class ResponseDeltaEvent(SSEEvent):
    """
    Final response chunk (real-time streaming).

    Frontend Action:
    - Match with response.start using response_id (if available)
    - Append text chunk to response area
    - Auto-scroll to latest content
    - Render markdown progressively
    - Show typing indicator
    """
    event_type: SSEEventType = SSEEventType.RESPONSE_DELTA
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "response_id": "",  # OpenAI's item_id (msg_XXX) for correlating start/delta/end events
            "delta": "",  # Text chunk to append
            "accumulated": ""  # Full text so far (for recovery)
        }
    )


class ResponseEndEvent(SSEEvent):
    """
    Response completed for this agent.

    Frontend Action:
    - Match with response.start using response_id (if available)
    - Finalize markdown rendering
    - Show total duration
    - If is_final_response=True: Display in "Final Response" box
    - Stop typing indicator

    The is_final_response flag determines which agent's response is shown
    in the dedicated "Final Response" UI element:
    - respond_directly=True  → specialist's response is final (specialist != router)
    - respond_directly=False → Router's synthesis is final (agent == router)

    This is set by lqc_data_team.py based on team configuration.
    """
    event_type: SSEEventType = SSEEventType.RESPONSE_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "response_id": "",          # OpenAI's item_id (msg_XXX) for correlating start/delta/end events
            "full_text": "",            # Complete response content
            "duration_ms": 0,           # Time taken to generate response
            "duration_display": "0.00s",  # Formatted duration
            "is_final_response": False  # True if this is THE final response for the UI
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
#                     FINAL RESPONSE EVENTS
#  Dedicated events for the Final Response box. These fire IN ADDITION to
#  the regular response.* events when is_final_response=True, allowing
#  the frontend to subscribe to these specifically without parsing every
#  response.delta event.
# ═══════════════════════════════════════════════════════════════════════════

class FinalResponseStartEvent(SSEEvent):
    """
    Final response streaming is beginning.

    Frontend Action:
    - Initialize final response box
    - Show streaming indicator in final response area
    - Know which agent is providing the final answer

    This event fires ONCE when the agent marked as final starts streaming.
    """
    event_type: SSEEventType = SSEEventType.FINAL_RESPONSE_START
    data: Dict[str, Any] = Field(
        default_factory=lambda: {}  # Agent info is in the base event
    )


class FinalResponseDeltaEvent(SSEEvent):
    """
    Final response chunk for the dedicated final response box.

    Frontend Action:
    - Append to final response box (not agent activity panel)
    - Render markdown progressively
    - Show typing indicator

    This is a dedicated stream - no need to check is_final_response flag.
    """
    event_type: SSEEventType = SSEEventType.FINAL_RESPONSE_DELTA
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "delta": "",        # Text chunk to append
            "accumulated": ""   # Full text so far
        }
    )


class FinalResponseEndEvent(SSEEvent):
    """
    Final response streaming complete.

    Frontend Action:
    - Finalize final response box
    - Stop streaming indicator
    - Show completion state

    This signals the final response box can show its complete state.
    """
    event_type: SSEEventType = SSEEventType.FINAL_RESPONSE_END
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "full_text": "",           # Complete final response
            "duration_ms": 0,          # Time to generate
            "duration_display": "0.00s"
        }
    )


class SessionEndedEvent(SSEEvent):
    """
    Query session completed.

    Frontend Action:
    - Stop all animations
    - Show total query time
    - Enable new query input
    - Highlight summary metrics
    - Correlate with session.started using question_answer_id

    Note: Contains same keys as session.started (plus duration/summary) for frontend consistency.
    """
    event_type: SSEEventType = SSEEventType.SESSION_ENDED
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "query": "",  # Same as session.started - the original query
            "session_id": "",  # Same as session.started - session identifier
            "question_answer_id": "",  # Same ID as session.started for correlation
            "verbosity": 1,  # Same as session.started - verbosity level
            "total_duration_ms": 0,
            "total_duration_display": "0.00s",
            "summary": {
                "agents_used": [],  # ["Router Agent", "Underwriting Agent"]
                "tools_executed": 0,
                "delegations": 0
            }
        }
    )


class ErrorEvent(SSEEvent):
    """
    Error occurred during query.

    Frontend Action:
    - Show error banner
    - Display error message
    - Provide retry option
    - Log for debugging
    """
    event_type: SSEEventType = SSEEventType.ERROR
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "error_type": "",  # "tool_error", "agent_error", "system_error"
            "message": "",
            "details": "",  # Technical details
            "recoverable": True
        }
    )


class CancelledEvent(SSEEvent):
    """
    Query was cancelled by user.

    Frontend Action:
    - Show cancellation message
    - Clear in-progress indicators
    - Clean up UI state
    - Enable new query input
    """
    event_type: SSEEventType = SSEEventType.CANCELLED
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "query_id": "",  # ID of cancelled query
            "message": "Query cancelled by user",
            "reason": "user_requested"  # Future: "timeout", "error", etc.
        }
    )


class ResponseFinalEvent(SSEEvent):
    """
    Final response with all accumulated data.

    This event contains the complete legacy-compatible response
    for MongoDB persistence and frontend state finalization.

    Frontend Action:
    - Store complete response data
    - Update conversation history
    - Enable response actions (copy, share, etc.)
    """
    event_type: SSEEventType = SSEEventType.RESPONSE_FINAL
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "status_code": 200,
            "user_id": "",
            "conversation_id": "",
            "company_id": "",
            "question_answer_id": "",
            "message": {
                "response": "",
                "sources": {},
                "graph": []
            },
            "message_is_complete": True,
            "response_origin": "KNOWLEDGE GRAPH",
            "web_search_status": "",
            "created_at": ""
        }
    )


class GraphDisplayEvent(SSEEvent):
    """
    Graph to be rendered by frontend.

    Emitted when agent includes [_graph_XXX] in response.
    The graph data comes from a prior get_*_data tool call.
    Graph metadata is looked up from the same source_mapping as citations.

    Uses MCP contract field names (2025-12-08):
    - name: Graph name (not graph_name)
    - graph_category: "Company" or "Fund" (Title Case, not entity_type)
    - company_id/fund_id: Separate fields (not entity_id)

    Frontend Action:
    - Render graph at the marker location [_graph_XXX]
    - Use name field to determine chart type
    - Look up full data from source_id in citation_index
    """
    event_type: SSEEventType = SSEEventType.GRAPH_DISPLAY
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "source_id": "",              # Full source ID: "_src_XXX"
            "graph_id": "",               # Full graph ID: "_graph_XXX"
            "type": "dataset",            # Source type identifier
            "name": "",                   # Graph name: "runway", "cac_payback"
            "graph_category": "",         # "Company" or "Fund" (Title Case)
            "company_id": None,           # Company ID or None
            "fund_id": None,              # Fund ID or None
            "tool_name": "",              # e.g., "get_runway_data"
            "fund_graph_selection": None  # "active", "exit", "both" or None
        }
    )


class CTAEvent(SSEEvent):
    """
    Call-to-action event for Deal Agent.

    Emitted when the Deal Agent determines an action should be taken
    (e.g., apply forecast adjustments, apply credit package changes).

    Frontend Action:
    - Display CTA button/action based on action type
    - Use data payload for action execution
    - auto_apply indicates if action should execute automatically

    Action Types:
    - "apply_forecast": Apply revenue forecast adjustments (data contains revenue array)
    - "apply_credit_package": Apply credit package changes
    - "none": No action required
    """
    event_type: SSEEventType = SSEEventType.CTA
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "action": "none",       # CTA action type
            "data": None,           # Action payload (e.g., adjusted revenue data)
            "auto_apply": False,    # Whether to auto-execute the action
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
#                           SSE FORMAT
# ═══════════════════════════════════════════════════════════════════════════

def format_sse(event: SSEEvent) -> str:
    """
    Format event as SSE message.

    SSE Format:
    event: <event_type>
    data: <json_payload>

    (blank line)
    """
    import json
    return f"event: {event.event_type.value}\ndata: {json.dumps(event.dict())}\n\n"


# ═══════════════════════════════════════════════════════════════════════════
#                           HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_agent_info(role: str) -> AgentInfo:
    """Get agent metadata by role"""
    agent_map = {
        "router": AgentInfo(
            role=AgentRole.ROUTER,
            name="Router Agent",
            icon="🔍",
            color="#3B82F6"  # Blue
        ),
        "underwriting": AgentInfo(
            role=AgentRole.UNDERWRITING,
            name="Underwriting Agent",
            icon="📊",
            color="#10B981"  # Green
        ),
        "origination": AgentInfo(
            role=AgentRole.ORIGINATION,
            name="Origination Agent",
            icon="💼",
            color="#8B5CF6"  # Purple
        ),
        "text2sql": AgentInfo(
            role=AgentRole.TEXT2SQL,
            name="Data Explorer",
            icon="🔬",
            color="#F59E0B"  # Amber
        ),
        "assistant": AgentInfo(
            role=AgentRole.ASSISTANT,
            name="LaSalle Wiki Tutor",
            icon="🎓",
            color="#0EA5E9"  # Sky
        ),
    }
    return agent_map.get(role, agent_map["assistant"])


def agent_name_to_role(name: str) -> str:
    """
    Convert human-readable agent name to role string.

    Handles case-insensitive matching and partial matches.

    Examples:
    - "Router Agent" -> "router"
    - "Underwriting Agent" -> "underwriting"
    - "Origination Agent" -> "origination"
    """
    if not name:
        return "router"

    name_lower = name.lower()

    if "underwriting" in name_lower:
        return "underwriting"
    elif "origination" in name_lower:
        return "origination"
    elif "text2sql" in name_lower or "data explorer" in name_lower:
        return "text2sql"
    elif "router" in name_lower:
        return "router"
    elif "tutor" in name_lower or "assistant" in name_lower or "wiki" in name_lower:
        return "assistant"

    # Default fallback
    return "assistant"


def get_tool_icon(tool_name: str) -> str:
    """Get icon for tool"""
    icon_map = {
        "recognize_entities": "🔍",
        "entity_disambiguation": "🎯",
        "company_info": "🏢",
        "credit_score": "📊",
        "scores": "📈",
        "metrics": "📉",
        "get_margin_analysis_data": "💹",
        "flow_data_ltm_yoy": "📊",
        "get_monthly_score_trend_data": "📈"
    }
    return icon_map.get(tool_name, "🔧")


def format_duration(duration_ms: float) -> str:
    """Format duration for display"""
    if duration_ms < 1000:
        return f"{duration_ms:.0f}ms"
    else:
        return f"{duration_ms/1000:.2f}s"


def compact_arguments(args: Dict[str, Any]) -> str:
    """Format arguments for compact display"""
    if not args:
        return "{}"

    # Show first 2 arguments
    items = list(args.items())[:2]
    formatted = ", ".join(f"{k}={repr(v)}" for k, v in items)

    if len(args) > 2:
        formatted += f", ... ({len(args)} total)"

    return formatted
