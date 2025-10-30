"""Handler for enforcing file access sandboxing on tool calls.

This handler intercepts tool calls from LLMs and validates that any file-changing
operations are restricted to within the detected project root directory. It prevents
accidental or malicious file modifications in sensitive system directories.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.session import Session
from src.core.interfaces.path_validator_interface import IPathValidator
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)


class FileSandboxingHandler(IToolCallHandler):
    """Handler for enforcing file access sandboxing on tool calls.

    This handler validates file paths in tool calls against the session's project
    root directory boundary. It blocks operations that attempt to access files
    outside the allowed project workspace.

    Attributes:
        _config: Sandboxing configuration
        _path_validator: Service for path validation operations
        _session_service: Service for retrieving session information
        _logger: Logger instance
        _tool_patterns: Compiled regex patterns for file-changing tools
        _excluded_patterns: Compiled regex patterns for excluded tools
        _blocked_count: Counter for blocked tool calls
        _allowed_count: Counter for allowed tool calls
        _validation_errors: Counter for validation errors
    """

    def __init__(
        self,
        config: SandboxingConfiguration,
        path_validator: IPathValidator,
        session_service: ISessionService,
        priority: int = 80,
    ):
        """Initialize the file sandboxing handler.

        Args:
            config: Sandboxing configuration
            path_validator: Service for path validation operations
            session_service: Service for retrieving session information
            priority: Handler priority (default 80, after tool access control at 90)
        """
        self._config = config
        self._path_validator = path_validator
        self._session_service = session_service
        self._priority = priority
        self._logger = logging.getLogger(__name__)

        # Compile tool patterns for efficient matching
        self._tool_patterns: list[re.Pattern[str]] = []
        self._excluded_patterns: list[re.Pattern[str]] = []

        # Initialize pattern matching
        self._compile_tool_patterns()
        self._compile_excluded_patterns()

        # Initialize metrics counters
        self._blocked_count = 0
        self._allowed_count = 0
        self._validation_errors = 0

        self._logger.info(
            f"FileSandboxingHandler initialized with {len(self._tool_patterns)} "
            f"tool patterns and {len(self._excluded_patterns)} excluded patterns"
        )

    @property
    def name(self) -> str:
        """The unique name of this handler."""
        return "file_sandboxing_handler"

    @property
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first)."""
        return self._priority

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        This handler evaluates file-changing tool calls when sandboxing is enabled
        and a project directory is set.

        Args:
            context: The tool call context.

        Returns:
            True if sandboxing is enabled and the tool is file-changing.
        """
        # Skip if sandboxing is disabled
        if not self._config.enabled:
            return False

        # Check if this is a file-changing tool
        return self._is_file_changing_tool(context.tool_name)

    def _compile_tool_patterns(self) -> None:
        """Compile regex patterns for file-changing tools.

        Combines default tool patterns from the configuration with any custom
        patterns provided by the user. Logs errors for invalid patterns but
        continues with valid ones.
        """
        all_patterns = (
            self._config.default_tool_patterns + self._config.custom_tool_patterns
        )

        for pattern in all_patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._tool_patterns.append(compiled)
            except re.error as e:
                self._logger.error(
                    f"Invalid tool pattern '{pattern}': {e}. "
                    "This pattern will be skipped."
                )

    def _compile_excluded_patterns(self) -> None:
        """Compile regex patterns for excluded tools.

        Tools matching these patterns will not be subject to sandboxing
        validation. Logs errors for invalid patterns but continues with
        valid ones.
        """
        for pattern in self._config.excluded_tools:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._excluded_patterns.append(compiled)
            except re.error as e:
                self._logger.error(
                    f"Invalid excluded tool pattern '{pattern}': {e}. "
                    "This pattern will be skipped."
                )

    def _is_file_changing_tool(self, tool_name: str) -> bool:
        """Check if a tool is a file-changing tool.

        First checks if the tool is in the excluded list, then checks if it
        matches any file-changing tool patterns.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool is a file-changing tool and not excluded,
            False otherwise
        """
        # Check if tool is excluded
        for pattern in self._excluded_patterns:
            if pattern.search(tool_name):
                self._logger.debug(
                    f"Tool '{tool_name}' matches excluded pattern, "
                    "skipping sandboxing"
                )
                return False

        # Check if tool matches file-changing patterns
        for pattern in self._tool_patterns:
            if pattern.search(tool_name):
                self._logger.debug(
                    f"Tool '{tool_name}' identified as file-changing tool"
                )
                return True

        return False

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle a tool call and enforce sandboxing if applicable.

        This is the main entry point for tool call validation. It performs
        the following checks:
        1. Retrieve session state and project directory
        2. Skip if no project directory is set
        3. Extract and validate file paths
        4. Block if any paths violate the boundary

        Args:
            context: The tool call context containing tool information

        Returns:
            ToolCallReactionResult indicating whether to block the tool call
        """
        tool_name = context.tool_name

        # Get session state
        try:
            session: Session = await self._session_service.get_session(
                context.session_id
            )
            state = session.state
        except Exception as e:
            self._logger.error(
                f"Failed to retrieve session {context.session_id}: {e}. "
                "Allowing tool call to proceed."
            )
            return ToolCallReactionResult(
                should_swallow=False,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "decision": "error_fail_open",
                    "error": str(e),
                },
            )

        # Check if project directory is set
        if not state.project_dir:
            self._logger.debug(
                f"Sandboxing skipped for session {context.session_id}: "
                "no project directory detected"
            )
            return ToolCallReactionResult(
                should_swallow=False,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "decision": "skipped_no_project_dir",
                    "session_id": context.session_id,
                },
            )

        project_root = Path(state.project_dir)

        # Extract file paths from arguments
        try:
            paths = self._path_validator.extract_paths_from_arguments(
                context.tool_arguments, self._config.path_parameter_names
            )
        except Exception as e:
            self._logger.error(
                f"Failed to extract paths from tool call '{tool_name}' "
                f"in session {context.session_id}: {e}"
            )
            self._validation_errors += 1

            # In strict mode, block on extraction failure
            if self._config.strict_mode:
                self._blocked_count += 1
                return self._generate_block_result(
                    context,
                    "Failed to extract file paths from tool call arguments",
                    project_root,
                )

            return ToolCallReactionResult(
                should_swallow=False,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "decision": "extraction_error_fail_open",
                    "error": str(e),
                },
            )

        if not paths:
            self._logger.debug(
                f"No file paths found in tool call '{tool_name}' "
                f"for session {context.session_id}"
            )
            return ToolCallReactionResult(
                should_swallow=False,
                metadata={
                    "handler": self.name,
                    "tool_name": tool_name,
                    "decision": "no_paths_found",
                    "session_id": context.session_id,
                },
            )

        # Validate each path
        violating_paths: list[str] = []

        for path_str in paths:
            try:
                # Normalize the path
                normalized_path = self._path_validator.normalize_path(
                    path_str, base_dir=str(project_root)
                )

                # Check if within boundary
                is_valid = self._path_validator.is_within_boundary(
                    normalized_path,
                    project_root,
                    allow_parent=self._config.allow_parent_access,
                )

                if not is_valid:
                    violating_paths.append(path_str)
                    self._logger.warning(
                        f"Sandboxing violation in session {context.session_id}: "
                        f"tool '{tool_name}' attempted to access '{path_str}' "
                        f"(normalized: '{normalized_path}') "
                        f"outside project root '{project_root}'"
                    )

            except ValueError as e:
                self._logger.error(
                    f"Path validation error for '{path_str}' "
                    f"in session {context.session_id}: {e}"
                )
                self._validation_errors += 1

                # In strict mode, treat validation errors as violations
                if self._config.strict_mode:
                    violating_paths.append(path_str)

        # Block if any violations found
        if violating_paths:
            self._blocked_count += 1
            return self._generate_block_result(
                context, self._format_violation_message(violating_paths), project_root
            )

        # All paths valid, allow the tool call
        self._allowed_count += 1
        self._logger.debug(
            f"Tool call '{tool_name}' allowed for session {context.session_id}: "
            f"all {len(paths)} path(s) within project root"
        )
        return ToolCallReactionResult(
            should_swallow=False,
            metadata={
                "handler": self.name,
                "tool_name": tool_name,
                "decision": "allowed",
                "paths_validated": len(paths),
                "session_id": context.session_id,
                "project_root": str(project_root),
            },
        )

    def _generate_block_result(
        self,
        context: ToolCallContext,
        reason: str,
        project_root: Path,
    ) -> ToolCallReactionResult:
        """Generate a block result for a sandboxing violation.

        Creates a ToolCallReactionResult that will swallow the tool call and
        return an error message to the LLM.

        Args:
            context: The tool call context to block
            reason: The reason for blocking (violation details)
            project_root: The project root directory path

        Returns:
            ToolCallReactionResult with error message
        """
        error_message = (
            f"Potential file-changing operation outside of the project root "
            f"folder detected. {reason}. "
            f"Please re-check file path and ensure you are not trying to edit "
            f"files outside of the allowed project folder: {project_root}"
        )

        self._logger.info(
            f"Blocked tool call '{context.tool_name}' for session "
            f"{context.session_id}: {reason}"
        )

        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=error_message,
            metadata={
                "handler": self.name,
                "tool_name": context.tool_name,
                "decision": "blocked",
                "reason": reason,
                "session_id": context.session_id,
                "project_root": str(project_root),
            },
        )

    def _format_violation_message(
        self,
        violating_paths: list[str],
    ) -> str:
        """Format a message describing path violations.

        Creates a human-readable message listing all paths that violated
        the sandboxing boundary.

        Args:
            violating_paths: List of paths that violated the boundary

        Returns:
            Formatted violation message
        """
        if len(violating_paths) == 1:
            return f"Path '{violating_paths[0]}' is outside the project root"
        else:
            paths_str = ", ".join(f"'{p}'" for p in violating_paths)
            return f"Paths {paths_str} are outside the project root"

    def get_metrics(self) -> dict[str, int]:
        """Get handler metrics.

        Returns:
            Dictionary containing:
                - blocked_count: Number of blocked tool calls
                - allowed_count: Number of allowed tool calls
                - validation_errors: Number of validation errors encountered
        """
        return {
            "blocked_count": self._blocked_count,
            "allowed_count": self._allowed_count,
            "validation_errors": self._validation_errors,
        }
