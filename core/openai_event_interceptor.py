"""
OpenAI Responses API Event Interceptor

This module provides a way to intercept raw OpenAI Responses API events
(ResponseStreamEvent objects) that are not currently exposed by Agno's
event system.

Usage:
    from core.openai_event_interceptor import OpenAIEventInterceptor

    # Create interceptor with custom handlers
    interceptor = OpenAIEventInterceptor()

    @interceptor.on("response.reasoning_summary.part")
    def handle_reasoning_summary(event):
        print(f"Reasoning summary: {event.part}")

    # Inject into agent's streaming response
    async with agent_with_interceptor(agent, interceptor) as enhanced_agent:
        await enhanced_agent.chat("your query")
"""

import contextvars
from typing import Dict, Callable, Any, Optional, AsyncGenerator
from functools import wraps
from collections import defaultdict

from utils.logger import logger


# Context variable to track the current session_id for this async task
# This is necessary because multiple concurrent requests may be using the same
# OpenAIResponses model instances
_current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_current_session_id',
    default=None
)


class OpenAIEventInterceptor:
    """
    Intercepts raw OpenAI Responses API events.

    Each interceptor is associated with a session_id for routing.

    This allows you to handle events that Agno doesn't currently process,
    such as:
    - response.reasoning_summary.part
    - response.reasoning_summary.done
    - response.reasoning_content.part
    - response.reasoning_content.done
    - And any future event types

    Example:
        interceptor = OpenAIEventInterceptor()

        @interceptor.on("response.reasoning_summary.part")
        def handle_summary(event):
            print(f"Summary chunk: {event.part}")

        @interceptor.on("response.reasoning_summary.done")
        def handle_summary_complete(event):
            print(f"Complete summary: {event.reasoning_summary}")
    """

    def __init__(self, enable_logging: bool = True):
        """
        Initialize the event interceptor.

        Args:
            enable_logging: Whether to log intercepted events
        """
        self.handlers: Dict[str, list[Callable]] = defaultdict(list)
        self.enable_logging = enable_logging
        self._event_counts: Dict[str, int] = defaultdict(int)

    def on(self, event_type: str) -> Callable:
        """
        Decorator to register an event handler.

        Args:
            event_type: OpenAI event type (e.g., "response.reasoning_summary.part")

        Returns:
            Decorator function

        Example:
            @interceptor.on("response.reasoning_summary.part")
            def my_handler(event):
                print(event.part)
        """
        def decorator(func: Callable) -> Callable:
            self.handlers[event_type].append(func)
            if self.enable_logging:
                logger.info(f"[OpenAIEventInterceptor] Registered handler for: {event_type}")
            return func
        return decorator

    def register(self, event_type: str, handler: Callable) -> None:
        """
        Register an event handler programmatically.

        Args:
            event_type: OpenAI event type
            handler: Handler function that takes event as parameter

        Example:
            def my_handler(event):
                print(event.part)

            interceptor.register("response.reasoning_summary.part", my_handler)
        """
        self.handlers[event_type].append(handler)
        if self.enable_logging:
            logger.info(f"[OpenAIEventInterceptor] Registered handler for: {event_type}")

    def intercept(self, event: Any) -> None:
        """
        Process an intercepted event by calling all registered handlers.

        Args:
            event: ResponseStreamEvent object from OpenAI
        """
        if not hasattr(event, 'type'):
            return

        event_type = event.type

        # Track event for statistics
        self._event_counts[event_type] += 1

        # Log if enabled - use INFO for tool-related events, DEBUG for others
        if self.enable_logging:
            if 'function_call' in event_type or 'tool' in event_type or 'output_item' in event_type:
                logger.info(f"[Interceptor] Captured event: {event_type}")
                # Log item details if available
                if hasattr(event, 'item'):
                    item = event.item
                    if hasattr(item, 'type'):
                        logger.info(f"[Interceptor]   → item.type = {item.type}")
                    if hasattr(item, 'name'):
                        logger.info(f"[Interceptor]   → item.name = {item.name}")
            else:
                logger.debug(f"[OpenAIEventInterceptor] Intercepted event: {event_type}")

        # Call all registered handlers for this event type
        if event_type in self.handlers:
            for handler in self.handlers[event_type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"[OpenAIEventInterceptor] Handler error for {event_type}: {e}", exc_info=True)

        # Call wildcard handlers (registered with "*")
        if "*" in self.handlers:
            for handler in self.handlers["*"]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"[OpenAIEventInterceptor] Wildcard handler error: {e}", exc_info=True)

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about intercepted events"""
        return dict(self._event_counts)

    def reset_stats(self) -> None:
        """Reset event statistics"""
        self._event_counts.clear()

    def clear_handlers(self, event_type: Optional[str] = None) -> None:
        """
        Clear registered handlers.

        Args:
            event_type: Specific event type to clear, or None to clear all
        """
        if event_type:
            self.handlers[event_type].clear()
            logger.info(f"[OpenAIEventInterceptor] Cleared handlers for: {event_type}")
        else:
            self.handlers.clear()
            logger.info(f"[OpenAIEventInterceptor] Cleared all handlers")


# Global registry of interceptors (to support multiple concurrent team instances)
# Maps session_id -> interceptor
_interceptor_registry: Dict[str, 'OpenAIEventInterceptor'] = {}
_original_parse_method = None
_patch_applied = False

def patch_openai_responses_streaming(interceptor: OpenAIEventInterceptor, session_id: str):
    """
    Monkey-patch OpenAIResponses to inject event interceptor.

    This function modifies the OpenAIResponses._parse_provider_response_delta
    method to call the interceptor before processing events.

    Supports multiple interceptors by maintaining a session-based registry.
    Each team instance can register its own interceptor with a unique session_id.

    Args:
        interceptor: OpenAIEventInterceptor instance to inject
        session_id: Unique session identifier to associate with this interceptor

    Example:
        interceptor = OpenAIEventInterceptor()
        patch_openai_responses_streaming(interceptor, "session_123")

        # Now all OpenAIResponses streaming will be intercepted
        async with LQCUnderwritingAgent(...) as agent:
            await agent.chat("query")
    """
    global _interceptor_registry, _original_parse_method, _patch_applied
    from agno.models.openai import OpenAIResponses

    # Register this interceptor with session_id
    _interceptor_registry[session_id] = interceptor
    logger.debug(f"[OpenAIEventInterceptor] Registered interceptor for session {session_id} (total: {len(_interceptor_registry)})")

    # Only apply the patch once
    if not _patch_applied:
        # Store original method
        _original_parse_method = OpenAIResponses._parse_provider_response_delta

        @wraps(_original_parse_method)
        def patched_parse(self, stream_event, assistant_message, tool_use):
            """Patched version that calls the interceptor for the current session"""
            # Get the session_id from context
            session_id = _current_session_id.get()

            if session_id and session_id in _interceptor_registry:
                interceptor = _interceptor_registry[session_id]
                try:
                    interceptor.intercept(stream_event)
                except Exception as e:
                    logger.error(f"[OpenAIEventInterceptor] Error in interceptor for session {session_id}: {e}", exc_info=True)

            # Call original method
            return _original_parse_method(self, stream_event, assistant_message, tool_use)

        # Apply patch
        OpenAIResponses._parse_provider_response_delta = patched_parse
        _patch_applied = True
        logger.info("[OpenAIEventInterceptor] Patched OpenAIResponses streaming (supports multiple interceptors)")


def set_session_context(session_id: str):
    """
    Set the session_id for the current async context.

    This should be called when entering a team's async context to ensure
    events are routed to the correct interceptor.

    Args:
        session_id: Unique session identifier

    Returns:
        Token that can be used to reset the context
    """
    return _current_session_id.set(session_id)


def unpatch_openai_responses_streaming(session_id: str):
    """
    Unregister an interceptor from the global registry.

    Should be called during team cleanup to prevent memory leaks and crosstalk.

    Args:
        session_id: Session identifier to unregister
    """
    global _interceptor_registry

    # Clear from context if it's the current one
    if _current_session_id.get() == session_id:
        _current_session_id.set(None)

    if session_id in _interceptor_registry:
        del _interceptor_registry[session_id]
        logger.info(f"[OpenAIEventInterceptor] Unregistered interceptor for session {session_id} (remaining: {len(_interceptor_registry)})")
    else:
        logger.warning(f"[OpenAIEventInterceptor] Attempted to unregister unknown session: {session_id}")


def get_active_interceptor_count() -> int:
    """
    Get the number of currently registered interceptors.

    Useful for monitoring memory usage and detecting leaks.

    Returns:
        Number of active interceptors
    """
    return len(_interceptor_registry)


async def async_streaming_with_interceptor(
    stream: AsyncGenerator,
    interceptor: OpenAIEventInterceptor
) -> AsyncGenerator:
    """
    Wrap an async stream to inject event interceptor.

    This is an alternative to monkey-patching that wraps the stream
    at a higher level.

    Args:
        stream: Original async stream
        interceptor: Event interceptor

    Yields:
        Same items as original stream

    Example:
        async def enhanced_chat(agent, query, interceptor):
            original_stream = agent.arun(query, stream=True)
            async for event in async_streaming_with_interceptor(original_stream, interceptor):
                # Handle event normally
                pass
    """
    async for event in stream:
        # Try to extract raw OpenAI event if available
        # This depends on Agno's internal structure
        if hasattr(event, '_raw_event'):
            interceptor.intercept(event._raw_event)

        yield event


# Example handlers for common reasoning summary events
def create_reasoning_summary_logger() -> OpenAIEventInterceptor:
    """
    Create an interceptor with pre-configured handlers for reasoning summary events.

    Returns:
        Configured OpenAIEventInterceptor

    Example:
        interceptor = create_reasoning_summary_logger()
        patch_openai_responses_streaming(interceptor)

        # Now reasoning summaries will be logged automatically
    """
    interceptor = OpenAIEventInterceptor(enable_logging=True)

    summary_parts = []

    @interceptor.on("response.reasoning_summary.part")
    def handle_summary_part(event):
        """Log reasoning summary parts as they stream"""
        if hasattr(event, 'part') and event.part:
            summary_parts.append(event.part)
            logger.info(f"[ReasoningSummary] Part: {event.part}")

    @interceptor.on("response.reasoning_summary.done")
    def handle_summary_done(event):
        """Log complete reasoning summary"""
        if hasattr(event, 'reasoning_summary'):
            logger.info(f"[ReasoningSummary] Complete: {event.reasoning_summary}")

        # Also log accumulated parts
        if summary_parts:
            full_summary = ''.join(summary_parts)
            logger.info(f"[ReasoningSummary] Accumulated: {full_summary}")
            summary_parts.clear()

    return interceptor


def create_all_events_logger() -> OpenAIEventInterceptor:
    """
    Create an interceptor that logs ALL OpenAI events.

    Useful for debugging and discovering what events are available.

    Returns:
        Configured OpenAIEventInterceptor

    Example:
        interceptor = create_all_events_logger()
        patch_openai_responses_streaming(interceptor)

        # Now all OpenAI events will be logged
    """
    interceptor = OpenAIEventInterceptor(enable_logging=True)

    @interceptor.on("*")
    def log_all_events(event):
        """Log all events with their attributes"""
        event_type = getattr(event, 'type', 'unknown')

        # Try to extract useful attributes
        attrs = {}
        for attr in ['part', 'delta', 'text', 'reasoning_summary', 'reasoning_content']:
            if hasattr(event, attr):
                value = getattr(event, attr)
                if value is not None:
                    attrs[attr] = value

        if attrs:
            logger.info(f"[OpenAIEvent] {event_type}: {attrs}")
        else:
            logger.info(f"[OpenAIEvent] {event_type}")

    return interceptor
