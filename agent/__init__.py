"""LaSalle Wiki Tutor agent — single-agent skeleton.

This package wraps an Agno `Agent` with the OpenAI event interception
patterns ported from lqc-ai-assistant-lib. The actual catalog tools will
be wired in later (Phase 4); for now there is a single dummy tool that
exercises the streaming pipeline end-to-end.

Public surface::

    from agent import WikiTutorAgent

    direct = WikiTutorAgent(session_id="...")
    direct.setup()
    await direct.async_setup()
    result = await direct.run("How can I help you?")
    await direct.cleanup()

Subscribe to events via ``direct.event_manager.subscribe(callback)``.
"""

from .wiki_tutor_agent import WikiTutorAgent, WikiTutorAgentConfig

__all__ = ["WikiTutorAgent", "WikiTutorAgentConfig"]
