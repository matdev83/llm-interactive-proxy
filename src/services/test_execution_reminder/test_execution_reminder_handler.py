"""Test execution reminder handler for tool call reactor system."""

from __future__ import annotations

import asyncio
import logging
from time import time
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)
from src.services.test_execution_reminder.file_modification_detector import (
    FileModificationDetector,
)
from src.services.test_execution_reminder.session_state import (
    TestExecutionSessionState,
)
from src.services.test_execution_reminder.test_runner_registry import (
    TestRunnerRegistry,
)

logger = logging.getLogger(__name__)

# Default steering message when tests haven't been run
DEFAULT_STEERING_MESSAGE = (
    "You have made code changes but haven't run tests yet. "
    "Please run test suite to verify your changes before completing this task. "
    "Once tests pass, you can proceed with task completion."
)


class TestExecutionReminderHandler(IToolCallHandler):
    """Handler that tracks file modifications and test executions.

    This handler maintains a "dirty state" indicator per session, tracking when
    files have been modified but tests haven't been run. When an agent attempts
    to signal task completion while in a dirty state, handler swallows
    tool call and returns a steering message reminding the agent to run tests.

    The handler integrates with tool call reactor pipeline and follows these
    principles:
    - Fail open: If uncertain, allow tool call through
    - Log and continue: Log errors but never crash the pipeline
    - Graceful degradation: Feature can be disabled without affecting the proxy
    - State reset: When in doubt, reset to clean state (safer than dirty)

    Thread-safety: Uses asyncio.Lock to protect shared state from concurrent
    async access. All methods that mutate shared state use async context.
    """

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        *,
        state_ttl_seconds: float = 1800.0,
        max_sessions: int = 1024,
        test_runner_registry: TestRunnerRegistry | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            message: Custom steering message (uses default if None)
            enabled: Whether the feature is enabled
            state_ttl_seconds: TTL for session state (default: 30 minutes)
            max_sessions: Maximum number of sessions to track
            test_runner_registry: Registry of test runner patterns (creates default if None)
        """
        self._message = message or DEFAULT_STEERING_MESSAGE
        self._enabled = enabled
        self._session_state: dict[str, TestExecutionSessionState] = {}
        self._state_ttl_seconds = max(float(state_ttl_seconds), 1.0)
        self._max_sessions = max(max_sessions, 1)
        self._test_runner_registry = test_runner_registry or TestRunnerRegistry()
        self._lock = asyncio.Lock()

        if self._enabled:
            logger.info(
                "Test execution reminder handler initialized (enabled) with %d test runner patterns",
                self._test_runner_registry.get_pattern_count(),
            )
        else:
            logger.info("Test execution reminder handler initialized (disabled)")

    @property
    def name(self) -> str:
        """The unique name of this handler."""
        return "test_execution_reminder_handler"

    @property
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first).

        Priority 90 places this handler:
        - Below pytest full-suite handler (95)
        - Above generic config steering handlers (typically 50-80)
        """
        return 90

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        This method determines whether the handler should process the tool call
        by checking:
        1. If the feature is enabled
        2. If the tool is a file modification (marks dirty)
        3. If the tool is a test execution (marks clean)
        4. If the tool is a completion signal in dirty state (triggers steering)

        Args:
            context: The tool call context

        Returns:
            True if this handler should process the tool call (only for completion
            signals in dirty state), False otherwise
        """
        # Early exit if disabled
        if not self._enabled:
            return False

        try:
            # Extract tool information
            tool_name = context.tool_name or ""
            tool_arguments = context.tool_arguments or {}

            # Check if this is a file modification tool
            if FileModificationDetector.is_file_modification(tool_name):
                # Mark session as dirty but don't handle (allow through)
                await self._mark_session_dirty(context.session_id, tool_name)
                return False

            # Check if this is a test execution command
            command = self._extract_command(tool_name, tool_arguments)
            if command:
                match = self._test_runner_registry.match_command(command)
                if match.is_match:
                    # Mark session as clean but don't handle (allow through)
                    await self._mark_session_clean(
                        context.session_id,
                        command,
                        match.language,
                        match.framework,
                    )
                    return False

            # Check if this is a completion tool call (by tool name only)
            # Note: finish_reason-based completion detection is now handled by EoS events
            # We only check tool names here for immediate steering before EoS event
            is_completion_tool = CompletionSignalDetector.is_completion_tool(tool_name)

            if is_completion_tool:

                # Get current state for logging
                state = await self._get_session_state(context.session_id)
                current_state = "dirty" if (state and state.is_dirty) else "clean"

                # Log completion tool detection
                logger.info(
                    "Completion tool detected: session=%s, current_state=%s, tool=%s",
                    context.session_id,
                    current_state,
                    tool_name,
                )

                # Only handle if session is dirty
                if state and state.is_dirty:
                    logger.debug(
                        "Completion tool in dirty state will trigger steering for session %s",
                        context.session_id,
                    )
                    return True
                else:
                    logger.debug(
                        "Completion tool in clean state, allowing through for session %s",
                        context.session_id,
                    )

            return False

        except Exception as e:
            # Fail open: log error and allow request through
            logger.error(
                "Error in can_handle for session %s: %s",
                context.session_id,
                str(e),
                exc_info=True,
            )
            return False

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle the tool call event.

        This method is called when can_handle returns True, which only happens
        for completion signals in dirty state. It swallows the tool call and
        returns a steering message reminding the agent to run tests.

        Args:
            context: The tool call context

        Returns:
            The reaction result with should_swallow=True and a steering message
        """
        # Verify feature is enabled
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        try:
            # Verify dirty state and completion signal
            state = await self._get_session_state(context.session_id)
            if not state or not state.is_dirty:
                return ToolCallReactionResult(should_swallow=False)

            # Check if this is a completion tool (by tool name only)
            # Note: finish_reason-based completion detection is now handled by EoS events
            is_completion_tool = CompletionSignalDetector.is_completion_tool(
                context.tool_name
            )

            if not is_completion_tool:

                return ToolCallReactionResult(should_swallow=False)

            # Create message preview (first 100 chars)
            message_preview = (
                self._message[:100] + "..."
                if len(self._message) > 100
                else self._message
            )

            # Log steering intervention with session ID and message preview
            logger.info(
                "Steering injection: session=%s, modifications=%d, last_modified_ago=%.2fs, message_preview='%s'",
                context.session_id,
                state.modification_count,
                time() - state.last_modification_time,
                message_preview,
            )

            # Return steering message
            return ToolCallReactionResult(
                should_swallow=True,
                replacement_response=self._message,
                metadata={
                    "handler": self.name,
                    "tool_name": context.tool_name,
                    "source": "test_execution_reminder",
                    "modification_count": state.modification_count,
                },
            )

        except Exception as e:
            # Fail open: log error and allow request through
            logger.error(
                "Error in handle for session %s: %s",
                context.session_id,
                str(e),
                exc_info=True,
            )
            return ToolCallReactionResult(should_swallow=False)

    async def _mark_session_dirty(
        self, session_id: str, tool_name: str | None = None
    ) -> None:
        """Mark a session as dirty (files modified).

        Args:
            session_id: The session ID to mark as dirty
            tool_name: The name of the file modification tool (for logging)
        """
        try:
            async with self._lock:
                # Prune expired/excess sessions before adding new ones
                self._prune_session_state()

                state = self._session_state.get(session_id)
                if not state:
                    state = TestExecutionSessionState()
                    self._session_state[session_id] = state

                state.mark_dirty()

            # Log file modification with tool name, session ID, and timestamp
            logger.info(
                "File modification tracked: tool=%s, session=%s, timestamp=%.2f, modification_count=%d",
                tool_name or "unknown",
                session_id,
                time(),
                state.modification_count,
            )

        except Exception as e:
            logger.error(
                "Error marking session %s as dirty: %s",
                session_id,
                str(e),
                exc_info=True,
            )

    async def _mark_session_clean(
        self,
        session_id: str,
        command: str,
        language: str | None,
        framework: str | None,
    ) -> None:
        """Mark a session as clean (tests run).

        Args:
            session_id: The session ID to mark as clean
            command: The test command that was executed
            language: The detected programming language
            framework: The detected test framework
        """
        try:
            async with self._lock:
                state = self._session_state.get(session_id)
                if not state:
                    state = TestExecutionSessionState()
                    self._session_state[session_id] = state

                state.mark_clean()

            logger.info(
                "Session %s marked as clean: test execution detected "
                "(language: %s, framework: %s, command: %s)",
                session_id,
                language or "unknown",
                framework or "unknown",
                command,
            )

        except Exception as e:
            logger.error(
                "Error marking session %s as clean: %s",
                session_id,
                str(e),
                exc_info=True,
            )

    async def _get_session_state(
        self, session_id: str
    ) -> TestExecutionSessionState | None:
        """Get the session state for a given session ID.

        Args:
            session_id: The session ID to get state for

        Returns:
            The session state or None if not found
        """
        try:
            async with self._lock:
                state = self._session_state.get(session_id)
                if state:
                    state.update_last_seen()

            return state

        except Exception as e:
            logger.error(
                "Error getting session state for %s: %s",
                session_id,
                str(e),
                exc_info=True,
            )
            return None

    def _prune_session_state(self, current_time: float | None = None) -> None:
        """Remove expired or excess session states.

        Note: This method must be called with self._lock already held.

        Args:
            current_time: Optional override for time.time() (used in tests).
        """
        now = current_time if current_time is not None else time()
        expired_sessions = [
            session_id
            for session_id, state in self._session_state.items()
            if now - state.last_seen > self._state_ttl_seconds
        ]

        if expired_sessions:
            for session_id in expired_sessions:
                self._session_state.pop(session_id, None)
            logger.info(
                "Session cleanup: pruned %d expired session(s) (TTL exceeded)",
                len(expired_sessions),
            )

        excess_count = len(self._session_state) - self._max_sessions
        if excess_count > 0:
            sorted_sessions = sorted(
                self._session_state.items(), key=lambda item: item[1].last_seen
            )
            pruned_sessions = []
            for session_id, _state in sorted_sessions[:excess_count]:
                self._session_state.pop(session_id, None)
                pruned_sessions.append(session_id)
            logger.info(
                "Session cleanup: pruned %d session(s) due to max_sessions limit (%d)",
                len(pruned_sessions),
                self._max_sessions,
            )

    def _extract_command(
        self, tool_name: str, tool_arguments: dict[str, Any]
    ) -> str | None:
        """Extract command from tool call arguments.

        This method attempts to extract a command string from various tool
        argument formats, supporting common shell execution tools.

        Args:
            tool_name: The name of the tool being called
            tool_arguments: The arguments passed to the tool

        Returns:
            The extracted command string or None if not found
        """
        try:
            # Normalize tool name for comparison
            normalized_tool_name = tool_name.lower().replace("_", "").replace("/", "")

            # Common shell execution tools
            shell_tools = {
                "bash",
                "cmd",
                "exec",
                "execcommand",
                "execute",
                "executecommand",
                "executepwsh",
                "localshell",
                "powershell",
                "pwsh",
                "python",
                "runcommand",
                "runshellcommand",
                "runterminalcmd",
                "shell",
                "terminal",
                "containerexec",
            }

            # Only extract commands from recognized shell tools
            if normalized_tool_name not in shell_tools:
                return None

            # Try common argument names for commands
            command_keys = ["command", "cmd", "script", "code", "input"]
            for key in command_keys:
                if key in tool_arguments:
                    value = tool_arguments[key]
                    if isinstance(value, str):
                        return value.strip()

            return None

        except Exception as e:
            logger.debug(
                "Error extracting command from tool %s: %s",
                tool_name,
                str(e),
                exc_info=True,
            )
            return None
