"""
Smart Event Renderer - Professional UX with verbosity levels

This renderer provides an amazing user experience by:
1. Buffering events until tool names are known
2. Collapsing related events into single-line displays
3. Supporting multiple verbosity levels (minimal, normal, verbose, debug)
4. Hiding noise and showing what matters
"""

import os
from typing import Optional, Dict, List
from enum import IntEnum

from .models import AgentEvent, EventType, AgentRole
from utils.logger import logger


class VerbosityLevel(IntEnum):
    """Verbosity levels for event display"""
    MINIMAL = 0    # Only final response
    NORMAL = 1     # Key operations (default)
    VERBOSE = 2    # Include reasoning and timing (buffered)
    STREAMING = 3  # Like VERBOSE but streams reasoning in real-time (for FastAPI/web)
    DEBUG = 4      # Everything including internal events


class Colors:
    """ANSI color codes for terminal output"""
    # Agent colors
    ROUTER = '\033[94m'       # Blue
    UNDERWRITING = '\033[92m'  # Green
    ORIGINATION = '\033[95m'   # Purple

    # Event type colors
    THINKING = '\033[90m'      # Gray
    TOOL = '\033[96m'          # Cyan
    DELEGATION = '\033[93m'    # Yellow
    RESPONSE = '\033[97m'      # White
    ERROR = '\033[91m'         # Red
    SUCCESS = '\033[92m'       # Green

    # Reset
    RESET = '\033[0m'
    BOLD = '\033[1m'

    @classmethod
    def disable(cls):
        """Disable colors (for non-terminal output)"""
        cls.ROUTER = ''
        cls.UNDERWRITING = ''
        cls.ORIGINATION = ''
        cls.THINKING = ''
        cls.TOOL = ''
        cls.DELEGATION = ''
        cls.RESPONSE = ''
        cls.ERROR = ''
        cls.SUCCESS = ''
        cls.RESET = ''
        cls.BOLD = ''


class SmartEventRenderer:
    """
    Smart event renderer with verbosity levels and event buffering.

    This renderer provides professional UX by:
    - Collapsing arguments + tool into single line
    - Buffering events until tool name is known
    - Supporting verbosity levels
    - Hiding noise (delegate_task_to_member arguments, redundant logs)

    Verbosity Levels:
    - MINIMAL (0): Only final response
    - NORMAL (1): Key operations - reasoning indicators + tool calls
    - VERBOSE (2): Full reasoning text (buffered) + tool details + timing
    - STREAMING (3): Like VERBOSE but streams reasoning in real-time (for FastAPI/web UIs)
    - DEBUG (4): All events including internal state changes

    **STREAMING mode** is designed for FastAPI/web frontends where reasoning must stream
    token-by-token to prevent the UI from appearing frozen during long reasoning periods.
    This provides a Claude Desktop-like experience with real-time feedback.
    """

    def __init__(
        self,
        verbosity: VerbosityLevel = VerbosityLevel.NORMAL,
        enable_colors: bool = True
    ):
        """
        Initialize the smart renderer.

        Args:
            verbosity: Verbosity level (0-3)
            enable_colors: Whether to use ANSI colors
        """
        self.verbosity = verbosity
        self.enable_colors = enable_colors

        if not enable_colors:
            Colors.disable()

        # Event buffering for tool name detection
        self._buffered_arguments: Dict[str, List[str]] = {}  # agent_name -> [arg chunks]
        self._current_tool_name: Dict[str, Optional[str]] = {}  # agent_name -> tool_name

        # Reasoning buffering
        self._reasoning_buffer: Dict[str, List[str]] = {}  # agent_name -> [reasoning chunks]
        self._reasoning_started: Dict[str, bool] = {}  # agent_name -> started

        logger.info(f"[SmartEventRenderer] Initialized with verbosity={verbosity.name}")

    # ============================================
    # Main Render Method
    # ============================================

    async def render(self, event: AgentEvent):
        """
        Render an event based on verbosity level.

        Args:
            event: The event to render
        """
        try:
            # DEBUG level: Show all events (but also process normally for streaming events)
            if self.verbosity >= VerbosityLevel.DEBUG:
                await self._render_debug(event)
                # Don't return early for REASONING_DELTA - let it stream in addition to debug output
                if event.event_type != EventType.REASONING_DELTA:
                    return

            # Dispatch to specific handlers based on event type
            handler_map = {
                # Reasoning
                EventType.REASONING_START: self._handle_reasoning_start,
                EventType.REASONING_DELTA: self._handle_reasoning_delta,
                EventType.REASONING_END: self._handle_reasoning_end,

                # Arguments (buffer until tool name known)
                EventType.ARGUMENTS_START: self._handle_arguments_start,
                EventType.ARGUMENTS_DELTA: self._handle_arguments_delta,
                EventType.ARGUMENTS_END: self._handle_arguments_end,

                # Tools
                EventType.TOOL_START: self._handle_tool_start,
                EventType.TOOL_END: self._handle_tool_end,

                # Delegation
                EventType.DELEGATION_START: self._handle_delegation_start,
                EventType.DELEGATION_END: self._handle_delegation_end,

                # Response
                EventType.RESPONSE_START: self._handle_response_start,
                EventType.RESPONSE_DELTA: self._handle_response_delta,
                EventType.RESPONSE_END: self._handle_response_end,

                # Error
                EventType.ERROR: self._handle_error,
            }

            handler = handler_map.get(event.event_type)
            if handler:
                handler(event)
            else:
                if self.verbosity >= VerbosityLevel.DEBUG:
                    logger.warning(f"[SmartEventRenderer] No handler for: {event.event_type}")

        except Exception as e:
            logger.error(f"[SmartEventRenderer] Error rendering event: {e}", exc_info=True)

    # ============================================
    # Reasoning Events
    # ============================================

    def _handle_reasoning_start(self, event: AgentEvent):
        """Handle reasoning start"""
        agent_name = event.agent_name

        # Initialize buffers
        self._reasoning_buffer[agent_name] = []
        self._reasoning_started[agent_name] = True

        # NORMAL+: Show thinking indicator
        if self.verbosity >= VerbosityLevel.NORMAL:
            color = self._get_agent_color(event.agent_role)
            logger.info(f"\n{color}🤔 {agent_name}{Colors.RESET}", end='', flush=True)

            # STREAMING/DEBUG: Show reasoning header for real-time streaming
            if self.verbosity in (VerbosityLevel.STREAMING, VerbosityLevel.DEBUG):
                logger.info(f"\n{Colors.THINKING}   ", end='', flush=True)

    def _handle_reasoning_delta(self, event: AgentEvent):
        """Handle reasoning delta - stream in STREAMING/DEBUG mode, buffer in VERBOSE mode"""
        if not event.content:
            return

        agent_name = event.agent_name

        # STREAMING/DEBUG: Stream reasoning in real-time (like Claude Desktop)
        if self.verbosity in (VerbosityLevel.STREAMING, VerbosityLevel.DEBUG):
            # Stream token-by-token for immediate feedback
            logger.info(event.content, end='', flush=True)
            # Still buffer for potential reuse (e.g., in final summary)
            if agent_name not in self._reasoning_buffer:
                self._reasoning_buffer[agent_name] = []
            self._reasoning_buffer[agent_name].append(event.content)
        elif self.verbosity >= VerbosityLevel.VERBOSE:
            # VERBOSE: Buffer reasoning text for display at the end
            if agent_name not in self._reasoning_buffer:
                self._reasoning_buffer[agent_name] = []
            self._reasoning_buffer[agent_name].append(event.content)

    def _handle_reasoning_end(self, event: AgentEvent):
        """Handle reasoning end"""
        agent_name = event.agent_name

        # STREAMING/DEBUG: Already streamed, just finish with timing
        if self.verbosity in (VerbosityLevel.STREAMING, VerbosityLevel.DEBUG):
            duration = event.duration_ms / 1000 if event.duration_ms else 0
            logger.info(f"{Colors.RESET}\n{Colors.THINKING}   (reasoning: {duration:.2f}s){Colors.RESET}")
        # VERBOSE: Show buffered reasoning text
        elif self.verbosity >= VerbosityLevel.VERBOSE:
            reasoning_text = ''.join(self._reasoning_buffer.get(agent_name, []))
            if reasoning_text:
                duration = event.duration_ms / 1000 if event.duration_ms else 0
                logger.info(f" ({duration:.2f}s)")
                logger.info(f"{Colors.THINKING}   {reasoning_text.strip()}{Colors.RESET}")
        # NORMAL: Just newline
        elif self.verbosity >= VerbosityLevel.NORMAL:
            logger.info()

        # Clean up
        self._reasoning_buffer.pop(agent_name, None)
        self._reasoning_started.pop(agent_name, None)

    # ============================================
    # Arguments Events (Buffered)
    # ============================================

    def _handle_arguments_start(self, event: AgentEvent):
        """Buffer arguments start"""
        agent_name = event.agent_name
        tool_name = event.tool_name or "unknown"

        # DEBUG
        if self.verbosity >= VerbosityLevel.DEBUG:
            logger.info(f"[SmartRenderer] Arguments start: agent={agent_name}, tool={tool_name}")

        # Initialize buffer
        self._buffered_arguments[agent_name] = []
        self._current_tool_name[agent_name] = tool_name

    def _handle_arguments_delta(self, event: AgentEvent):
        """Buffer arguments delta"""
        if not event.content:
            return

        agent_name = event.agent_name

        # DEBUG
        if self.verbosity >= VerbosityLevel.DEBUG:
            logger.info(f"[SmartRenderer] Arguments delta: agent={agent_name}, content={event.content[:50]}")

        # Buffer arguments
        if agent_name not in self._buffered_arguments:
            self._buffered_arguments[agent_name] = []
        self._buffered_arguments[agent_name].append(event.content)

    def _handle_arguments_end(self, event: AgentEvent):
        """
        Arguments end - but DON'T emit yet!

        Wait for tool_start which will give us the real tool name.
        If tool_start already happened, emit now.
        """
        agent_name = event.agent_name
        buffered = self._buffered_arguments.get(agent_name, [])

        # DEBUG
        if self.verbosity >= VerbosityLevel.DEBUG:
            logger.info(f"[SmartRenderer] Arguments end: agent={agent_name}, buffered={''.join(buffered)[:100]}")

    # ============================================
    # Tool Events
    # ============================================

    def _handle_tool_start(self, event: AgentEvent):
        """
        Handle tool start - emit combined tool + arguments display.

        This is where we show the tool call with its arguments in one line.
        """
        agent_name = event.agent_name
        tool_name = event.tool_name or "unknown"

        # DEBUG
        if self.verbosity >= VerbosityLevel.DEBUG:
            logger.info(f"[SmartRenderer] Tool start: agent={agent_name}, tool={tool_name}")
            logger.info(f"[SmartRenderer] Buffered args for {agent_name}: {self._buffered_arguments.get(agent_name, [])}")

        # Skip delegate_task_to_member (shown as delegation event instead)
        if tool_name == 'delegate_task_to_member':
            self._buffered_arguments.pop(agent_name, None)
            self._current_tool_name.pop(agent_name, None)
            if self.verbosity >= VerbosityLevel.DEBUG:
                logger.info(f"[SmartRenderer] Skipping delegate_task_to_member display")
            return

        # Get arguments from two possible sources:
        # 1. Buffered from arguments events (preferred for streaming)
        # 2. From event.tool_arguments (fallback)
        args_chunks = self._buffered_arguments.pop(agent_name, [])

        if args_chunks:
            # Use buffered arguments (from streaming)
            args_str = ''.join(args_chunks)
        elif event.tool_arguments:
            # Use arguments from event (fallback)
            import json
            args_str = json.dumps(event.tool_arguments)
        else:
            # No arguments available
            args_str = "{}"

        # DEBUG
        if self.verbosity >= VerbosityLevel.DEBUG:
            logger.info(f"[SmartRenderer] Final args_str: {args_str[:100]}")
            logger.info(f"[SmartRenderer] Used buffered: {bool(args_chunks)}, Used event.tool_arguments: {bool(event.tool_arguments)}")

        # Clean up
        self._current_tool_name.pop(agent_name, None)

        # MINIMAL: Don't show tools
        if self.verbosity < VerbosityLevel.NORMAL:
            return

        # Get colors
        agent_color = self._get_agent_color(event.agent_role)

        # NORMAL/STREAMING: Show one-line tool call (compact)
        if self.verbosity in (VerbosityLevel.NORMAL, VerbosityLevel.STREAMING):
            # Compact format: 🔍 tool_name(key_args)
            icon = self._get_tool_icon(tool_name)
            compact_args = self._compact_args(args_str)
            # STREAMING: Suppress newline so timing can be appended on same line
            # NORMAL: logger.info with newline (no timing will be appended)
            if self.verbosity == VerbosityLevel.STREAMING:
                logger.info(f"  {icon} {tool_name}{compact_args}", end='', flush=True)
            else:
                logger.info(f"  {icon} {tool_name}{compact_args}")

        # VERBOSE/DEBUG: Show full tool call with details
        elif self.verbosity in (VerbosityLevel.VERBOSE, VerbosityLevel.DEBUG):
            color = self._get_agent_color(event.agent_role)
            logger.info(f"{color}  └─ {tool_name}{Colors.RESET}")
            logger.info(f"{Colors.TOOL}     Args: {args_str}{Colors.RESET}")

    def _handle_tool_end(self, event: AgentEvent):
        """Handle tool end"""
        tool_name = event.tool_name or "unknown"
        duration = event.duration_ms / 1000 if event.duration_ms else 0

        # Skip delegate_task_to_member
        if tool_name == 'delegate_task_to_member':
            return

        # STREAMING: Show inline timing (compact)
        if self.verbosity == VerbosityLevel.STREAMING:
            # Skip tool_end with 0.00s duration - a corrected event with actual timing will follow
            # (This handles the race condition where OpenAI events fire before tool execution completes)
            if duration < 0.01:  # Less than 10ms is effectively 0 (OpenAI event timing)
                return
            logger.info(f" took {duration:.2f}s")

        # VERBOSE/DEBUG: Show timing and result on separate lines (REQUIRED for VERBOSE)
        elif self.verbosity in (VerbosityLevel.VERBOSE, VerbosityLevel.DEBUG):
            result_preview = self._preview_result(event.tool_result)
            logger.info(f"{Colors.SUCCESS}     Result: {result_preview}{Colors.RESET}")
            logger.info(f"{Colors.THINKING}     Time: {duration:.2f}s{Colors.RESET}")

    # ============================================
    # Delegation Events
    # ============================================

    def _handle_delegation_start(self, event: AgentEvent):
        """Handle delegation start"""
        # MINIMAL: Don't show delegation
        if self.verbosity < VerbosityLevel.NORMAL:
            return

        from_agent = event.delegation_from or event.agent_name
        to_agent = event.delegation_to or "unknown"

        # NORMAL+: Show delegation
        logger.info(f"\n{Colors.DELEGATION}👉 Delegating to {to_agent}{Colors.RESET}")

        # VERBOSE+: Show task (truncate only in VERBOSE=2, show full in STREAMING=3/DEBUG=4)
        if self.verbosity >= VerbosityLevel.VERBOSE and event.delegation_task:
            task = event.delegation_task
            # Only truncate in VERBOSE mode (level 2), show full in STREAMING/DEBUG (level 3+)
            if self.verbosity == VerbosityLevel.VERBOSE and len(task) > 100:
                task = task[:97] + "..."
            logger.info(f"{Colors.THINKING}   Task: {task}{Colors.RESET}")

    def _handle_delegation_end(self, event: AgentEvent):
        """Handle delegation end"""
        # VERBOSE: Show completion timing
        if self.verbosity >= VerbosityLevel.VERBOSE:
            duration = event.duration_ms / 1000 if event.duration_ms else 0
            logger.info(f"{Colors.SUCCESS}✅ Delegation complete ({duration:.2f}s){Colors.RESET}")

    # ============================================
    # Response Events
    # ============================================

    def _handle_response_start(self, event: AgentEvent):
        """Handle response start"""
        # Always show response, even in MINIMAL mode
        #logger.info(f"\n{Colors.RESPONSE}💬 {Colors.RESET}", end='', flush=True)

    def _handle_response_delta(self, event: AgentEvent):
        """Handle response delta (stream content)"""
        #if event.content:
            # Don't use color codes here - they get captured back into the response stream
            # Just logger.info the content directly
            #logger.info(event.content, end='', flush=True)

    def _handle_response_end(self, event: AgentEvent):
        """Handle response end"""
        # VERBOSE: Show response timing
        if self.verbosity >= VerbosityLevel.VERBOSE:
            duration = event.duration_ms / 1000 if event.duration_ms else 0
            logger.info(f"\n{Colors.THINKING}(response time: {duration:.2f}s){Colors.RESET}")
        else:
            logger.info()  # Just newline

    # ============================================
    # Error Events
    # ============================================

    def _handle_error(self, event: AgentEvent):
        """Handle error event"""
        # Always show errors
        logger.error(f"\n{Colors.ERROR}❌ Error: {event.agent_name}{Colors.RESET}")
        if event.error_message:
            logger.error(f"{Colors.ERROR}{event.error_message}{Colors.RESET}")

        # VERBOSE+: Show error details
        if self.verbosity >= VerbosityLevel.VERBOSE and event.error_type:
            logger.error(f"{Colors.THINKING}Type: {event.error_type}{Colors.RESET}")

    # ============================================
    # DEBUG Rendering
    # ============================================

    async def _render_debug(self, event: AgentEvent):
        """Render event in DEBUG mode (show everything)"""
        import json
        from datetime import datetime

        # Timestamp
        timestamp = event.timestamp.strftime("%H:%M:%S.%f")[:-3]

        # Event header
        logger.info(f"\n{Colors.THINKING}[{timestamp}] {event.event_type.value.upper()}{Colors.RESET}")
        logger.info(f"  Agent: {event.agent_name} ({event.agent_role.value})")
        logger.info(f"  Event ID: {event.event_id}")

        # Content
        if event.content:
            content_preview = event.content if len(event.content) < 100 else event.content[:97] + "..."
            logger.info(f"  Content: {content_preview}")

        # Tool info
        if event.tool_name:
            logger.info(f"  Tool: {event.tool_name}")
            if event.tool_arguments:
                logger.info(f"  Args: {json.dumps(event.tool_arguments, indent=2)}")
            if event.tool_result:
                result_str = str(event.tool_result)
                result_preview = result_str if len(result_str) < 100 else result_str[:97] + "..."
                logger.info(f"  Result: {result_preview}")

        # Delegation info
        if event.delegation_from or event.delegation_to:
            logger.info(f"  Delegation: {event.delegation_from} → {event.delegation_to}")
            if event.delegation_task:
                logger.info(f"  Task: {event.delegation_task[:100]}...")

        # Timing
        if event.duration_ms:
            logger.info(f"  Duration: {event.duration_ms / 1000:.2f}s")

        # Error info
        if event.error_message:
            logger.info(f"  Error: {event.error_message}")

        logger.info(f"{Colors.THINKING}{'─' * 80}{Colors.RESET}")

    # ============================================
    # Helper Methods
    # ============================================

    def _get_agent_color(self, agent_role: AgentRole) -> str:
        """Get color for agent"""
        color_map = {
            AgentRole.ROUTER: Colors.ROUTER,
            AgentRole.UNDERWRITING: Colors.UNDERWRITING,
            AgentRole.ORIGINATION: Colors.ORIGINATION,
        }
        return color_map.get(agent_role, Colors.RESET)

    def _get_tool_icon(self, tool_name: str) -> str:
        """Get emoji icon for tool"""
        icon_map = {
            'recognize_entities': '🔍',
            'company_info': '🏢',
            'get_credit_score': '📊',
            'get_margin_analysis_data': '📈',
            'flow_data_ltm_yoy': '📉',
            'delegate_task_to_member': '👉',
        }
        return icon_map.get(tool_name, '🔧')

    def _compact_args(self, args_str: str) -> str:
        """Create compact representation of arguments"""
        try:
            import json
            args = json.loads(args_str)

            # If no args, return empty
            if not args:
                return "()"

            # For small args, show inline
            if len(args_str) < 50:
                return f"({args_str})"

            # For large args, show key fields only
            key_fields = []
            for key in ['company_id', 'entities', 'member_id', 'task']:
                if key in args:
                    value = args[key]
                    if isinstance(value, str) and len(value) > 30:
                        value = value[:27] + "..."
                    key_fields.append(f"{key}={repr(value)}")

            if key_fields:
                return f"({', '.join(key_fields)})"

            return "(…)"

        except Exception:
            # If JSON parsing fails, just show ...
            return "(…)"

    def _preview_result(self, result) -> str:
        """Create preview of tool result"""
        if result is None:
            return "None"

        result_str = str(result)
        if len(result_str) > 80:
            return result_str[:77] + "..."
        return result_str


# ============================================
# Convenience Function
# ============================================

def create_smart_renderer(
    verbosity: Optional[int] = None,
    enable_colors: bool = True
) -> SmartEventRenderer:
    """
    Create a smart event renderer with verbosity control.

    Args:
        verbosity: Verbosity level (0=minimal, 1=normal, 2=verbose, 3=debug)
                   If None, reads from environment variable LQC_VERBOSITY (default: 1)
        enable_colors: Whether to use ANSI colors

    Returns:
        Configured SmartEventRenderer

    Example:
        >>> renderer = create_smart_renderer(verbosity=2)
        >>> manager.subscribe(renderer.render)
    """
    # Get verbosity from env if not provided
    if verbosity is None:
        verbosity_str = os.getenv('LQC_VERBOSITY', '1')
        try:
            verbosity = int(verbosity_str)
        except ValueError:
            verbosity = 1

    # Clamp to valid range (0-4: MINIMAL, NORMAL, VERBOSE, STREAMING, DEBUG)
    verbosity = max(0, min(4, verbosity))

    return SmartEventRenderer(
        verbosity=VerbosityLevel(verbosity),
        enable_colors=enable_colors
    )
