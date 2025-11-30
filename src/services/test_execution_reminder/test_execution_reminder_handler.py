"""Test execution reminder handler for tool call reactor system."""

from __future__ import annotations

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
    "Please run the test suite to verify your changes before completing this task. "
    "Once tests pass, you can proceed with task completion."
)


class TestExecutionReminderHandler(IToolCallHandler):
    """Handler that tracks file modifications and test executions.

    This handler maintains a "dirty state" indicator per session, tracking when
    files have been modified but tests haven't been run. When an agent attempts
    to signal task completion while in a dirty state, the handler swallows the
    tool call and returns a steering message reminding the agent to run tests.

    The handler integrates with the tool call reactor pipeline and follows these
    principles:
    - Fail open: If uncertain, allow the tool call through
    - Log and continue: Log errors but never crash the pipeline
    - Graceful degradation: Feature can be disabled without affecting proxy
    - State reset: When in doubt, reset to clean state (safer than dirty)
    """

    def __init__(
        self,
        message: str | None = None,
        enabled: bool = True,
        *,
        state_ttl_seconds: int = 1800,
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
        self._state_ttl_seconds = max(state_ttl_seconds, 1)
        self._max_sessions = max(max_sessions, 1)
        self._test_runner_registry = test_runner_registry or TestRunnerRegistry()

        if self._enabled:
            logger.info(
                "Test execution reminder handler initialized (enabled) with %d test runner patterns",
                len(self._test_runner_registry._patterns),
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
                self._mark_session_dirty(context.session_id, tool_name)
                return False

            # Check if this is a test execution command
            command = self._extract_command(tool_name, tool_arguments)
            if command:
                is_test, language, framework = self._test_runner_registry.match_command(
                    command
                )
                if is_test:
                    # Mark session as clean but don't handle (allow through)
                    self._mark_session_clean(
                        context.session_id, command, language, framework
                    )
                    return False

            # Check if this is a completion signal
            # Extract finish_reason and metadata if available
            finish_reason = self._extract_finish_reason(context.full_response)
            metadata = self._extract_metadata(context.full_response)
            is_completion = CompletionSignalDetector.is_completion_signal(
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                finish_reason=finish_reason,
                metadata=metadata,
            )

            if is_completion:
                # Get current state for logging
                state = self._get_session_state(context.session_id)
                current_state = "dirty" if (state and state.is_dirty) else "clean"

                # Determine detection reason
                is_tool_match = CompletionSignalDetector._is_completion_tool(tool_name)
                is_finish_reason_match = CompletionSignalDetector._is_finish_reason(
                    finish_reason
                )

                if is_tool_match and is_finish_reason_match:
                    reason = "tool_name_and_finish_reason"
                elif is_tool_match:
                    reason = "tool_name"
                elif is_finish_reason_match:
                    reason = "finish_reason"
                else:
                    reason = "unknown"

                # Log completion signal detection with reason and current state
                logger.info(
                    "Completion signal detected: session=%s, reason=%s, current_state=%s, tool=%s, finish_reason=%s",
                    context.session_id,
                    reason,
                    current_state,
                    tool_name,
                    finish_reason,
                )

                # Only handle if session is dirty
                if state and state.is_dirty:
                    logger.debug(
                        "Completion signal in dirty state will trigger steering for session %s",
                        context.session_id,
                    )
                    return True
                else:
                    logger.debug(
                        "Completion signal in clean state, allowing through for session %s",
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
            state = self._get_session_state(context.session_id)
            if not state or not state.is_dirty:
                return ToolCallReactionResult(should_swallow=False)

            # Extract finish_reason and metadata for completion signal verification
            finish_reason = self._extract_finish_reason(context.full_response)
            metadata = self._extract_metadata(context.full_response)
            is_completion = CompletionSignalDetector.is_completion_signal(
                tool_name=context.tool_name,
                tool_arguments=context.tool_arguments,
                finish_reason=finish_reason,
                metadata=metadata,
            )

            if not is_completion:
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

    def _mark_session_dirty(
        self, session_id: str, tool_name: str | None = None
    ) -> None:
        """Mark a session as dirty (files modified).

        Args:
            session_id: The session ID to mark as dirty
            tool_name: The name of the file modification tool (for logging)
        """
        try:
            now = time()
            self._prune_session_state(now)

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
                now,
                state.modification_count,
            )

        except Exception as e:
            logger.error(
                "Error marking session %s as dirty: %s",
                session_id,
                str(e),
                exc_info=True,
            )

    def _mark_session_clean(
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
            now = time()
            self._prune_session_state(now)

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

    def _get_session_state(self, session_id: str) -> TestExecutionSessionState | None:
        """Get the session state for a given session ID.

        Args:
            session_id: The session ID to get state for

        Returns:
            The session state or None if not found
        """
        try:
            now = time()
            self._prune_session_state(now)

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

    def _prune_session_state(self, now: float) -> None:
        """Prune expired session state based on TTL and max sessions.

        This method removes session states that haven't been accessed within
        the TTL period and enforces the maximum session limit by removing
        the oldest sessions.

        Args:
            now: Current timestamp
        """
        try:
            # Remove expired sessions based on TTL
            expired: list[str] = []
            for session_id, state in self._session_state.items():
                if now - state.last_seen > self._state_ttl_seconds:
                    expired.append(session_id)

            if expired:
                for session_id in expired:
                    del self._session_state[session_id]
                logger.info(
                    "Session cleanup: pruned %d expired session(s) (TTL: %ds, remaining: %d)",
                    len(expired),
                    self._state_ttl_seconds,
                    len(self._session_state),
                )

            # Enforce max sessions limit
            if len(self._session_state) <= self._max_sessions:
                return

            # Remove oldest sessions to cap memory usage
            sorted_sessions = sorted(
                self._session_state.items(), key=lambda item: item[1].last_seen
            )
            remove_count = len(self._session_state) - self._max_sessions
            for session_id, _ in sorted_sessions[:remove_count]:
                del self._session_state[session_id]

            logger.warning(
                "Session cleanup: pruned %d session(s) to enforce max limit (max: %d, remaining: %d)",
                remove_count,
                self._max_sessions,
                len(self._session_state),
            )

        except Exception as e:
            logger.error(
                "Error pruning session state: %s",
                str(e),
                exc_info=True,
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
            )
            return None

    def _extract_finish_reason(self, full_response: Any) -> str | None:
        """Extract finish_reason from the full LLM response.

        This method attempts to extract the finish_reason field from streaming
        responses, which indicates the end of the LLM's response.

        Args:
            full_response: The full response from the LLM

        Returns:
            The finish_reason value or None if not found
        """
        try:
            if not isinstance(full_response, dict):
                return None

            # Check top-level finish_reason
            if "finish_reason" in full_response:
                return full_response["finish_reason"]

            # Check in choices array (OpenAI format)
            choices = full_response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason:
                        return finish_reason

            # Check in metadata
            metadata = full_response.get("metadata", {})
            if isinstance(metadata, dict) and "finish_reason" in metadata:
                return metadata["finish_reason"]

            return None

        except Exception as e:
            logger.debug(
                "Error extracting finish_reason: %s",
                str(e),
            )
            return None

    def _extract_metadata(self, full_response: Any) -> dict[str, Any] | None:
        """Extract metadata from the full LLM response.

        This method attempts to extract metadata that may contain finish_reason
        or other completion indicators.

        Args:
            full_response: The full response from the LLM

        Returns:
            The metadata dict or None if not found
        """
        try:
            if not isinstance(full_response, dict):
                return None

            # Check for metadata field
            if "metadata" in full_response:
                metadata = full_response["metadata"]
                if isinstance(metadata, dict):
                    return metadata

            # Return the full response as metadata if it's a dict
            # This allows checking for finish_reason at the top level
            return full_response

        except Exception as e:
            logger.debug(
                "Error extracting metadata: %s",
                str(e),
            )
            return None
