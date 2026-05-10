"""
Event System — unified event handling for the LaSalle catalog assistant.

Ported from lqc-ai-assistant-lib/events/. Drops the deal-specific
adapters (DealSSEAdapter, DealAgentStreamHandler) — they live alongside
a multi-agent team that this skeleton does not include.

Usage:
    from events import AgentEvent, EventManager, AgentContextTracker
    from events import EventType, AgentRole

    manager = EventManager()
    tracker = AgentContextTracker()

    async def my_callback(event: AgentEvent):
        print(f"Event: {event.event_type} from {event.agent_name}")

    manager.subscribe(my_callback)

    await manager.emit_reasoning_start(tracker.current_agent)
    await manager.emit_reasoning_delta(tracker.current_agent, "Thinking...")
    await manager.emit_reasoning_end(tracker.current_agent)
"""

from .models import (
    AgentEvent,
    AgentRole,
    EventType,
    ParallelContext,
    get_agent_name,
    parse_member_id_to_role,
)

from .manager import EventManager
from .tracker import (
    ActiveAgentRun,
    AgentContextTracker,
    ParallelAgentTracker,
)
from .store import EventRecord, EventStore
from .replay import (
    get_session_events_for_api,
    get_session_stats_for_api,
    replay_session_stream,
)

# Conditionally import smart_renderer only when terminal logs are enabled
from config.settings import PROJECT_SETTINGS

__all__ = [
    # Models
    "AgentEvent",
    "EventType",
    "AgentRole",
    "ParallelContext",
    "get_agent_name",
    "parse_member_id_to_role",

    # Manager
    "EventManager",

    # Trackers
    "AgentContextTracker",
    "ParallelAgentTracker",
    "ActiveAgentRun",

    # Store (event sourcing)
    "EventStore",
    "EventRecord",

    # Replay API utilities
    "get_session_events_for_api",
    "get_session_stats_for_api",
    "replay_session_stream",
]

if PROJECT_SETTINGS.TERMINAL_LOGS_ENABLED:
    from .smart_renderer import SmartEventRenderer, VerbosityLevel, create_smart_renderer

    __all__.extend([
        "SmartEventRenderer",
        "create_smart_renderer",
        "VerbosityLevel",
    ])

__version__ = "1.0.0"
