"""File sandboxing handler for tool call reactor system.

This module implements the FileSandboxingHandler that intercepts file-changing
tool calls and validates that they operate within the project directory boundary.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.interfaces.path_validator_interface import IPathValidator
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FileSandboxingHandler(IToolCallHandler):
    """Handler that enforces file access sandboxing for tool calls.

    This handler intercepts file-changing tool calls and validates that the
    file paths are within the project directory boundary. If a violation is
    detected, the tool call is blocked and an error message is returned.
    """

    def __init__(
        self,
        config: SandboxingConfiguration,
        path_validator: IPathValidator,
        session_service: ISessionService,
    ) -> None:
        """Initialize the file sandboxing handler.

        Args:
            config: Sandboxing configuration
            path_validator: Path validation service
            session_service: Session service for retrieving session state
        """
        self._config = config
        self._validator = path_validator
        self._session_service = session_service

        # Compile tool patterns for efficient matching
        all_patterns = list(self._config.default_tool_patterns) + list(
            self._config.custom_tool_patterns
        )
        self._tool_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in all_patterns
        ]

        # Compile exclusion patterns
        self._excluded_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self._config.excluded_tools
        ]

        # Metrics tracking
        self._blocked_count = 0
        self._allowed_count = 0
        self._validation_errors = 0

        logger.info(
            f"FileSandboxingHandler initialized with {len(self._tool_patterns)} tool patterns "
            f"and {len(self._excluded_patterns)} exclusion patterns"
        )

    @property
    def name(self) -> str:
        """The unique name of this handler."""
        return "file_sandboxing_handler"

    @property
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first).

        File sandboxing runs at priority 80 to ensure it executes before
        most other handlers but after critical security handlers.
        """
        return 80

    def get_metrics(self) -> dict[str, int]:
        """Get metrics for monitoring handler performance.

        Returns:
            Dictionary containing blocked_count, allowed_count, and validation_errors
        """
        return {
            "blocked_count": self._blocked_count,
            "allowed_count": self._allowed_count,
            "validation_errors": self._validation_errors,
        }

    def _is_file_changing_tool(self, tool_name: str) -> bool:
        """Check if a tool name matches file-changing tool patterns.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool is a file-changing tool
        """
        # Check if tool is excluded
        for pattern in self._excluded_patterns:
            if pattern.search(tool_name):
                logger.debug(f"Tool '{tool_name}' is excluded from sandboxing")
                return False

        # Check if tool matches file-changing patterns
        return any(pattern.search(tool_name) for pattern in self._tool_patterns)

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        Args:
            context: The tool call context

        Returns:
            True if this is a file-changing tool call that should be validated
        """
        # Only handle if sandboxing is enabled
        if not self._config.enabled:
            return False

        # Check if this is a file-changing tool
        return self._is_file_changing_tool(context.tool_name)

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle the tool call by validating file paths."""
        try:
            session = await self._session_service.get_session(context.session_id)
            project_dir = session.state.project_dir

            if not project_dir:
                logger.debug(
                    f"No project directory set for session {context.session_id}, allowing tool call '{context.tool_name}'"
                )
                return ToolCallReactionResult(
                    should_swallow=False,
                    metadata={"decision": "skipped_no_project_dir"},
                )

            project_root = Path(project_dir).resolve()

            try:
                paths = self._validator.extract_paths_from_arguments(
                    context.tool_arguments, self._config.path_parameter_names
                )
            except ValueError as e:
                logger.error(
                    f"Path extraction failed for tool '{context.tool_name}': {e}",
                    exc_info=True,
                )
                self._validation_errors += 1
                if self._config.strict_mode:
                    self._blocked_count += 1
                    return ToolCallReactionResult(
                        should_swallow=True,
                        replacement_response=f"File operation blocked: Failed to extract file paths. Error: {e}",
                        metadata={
                            "decision": "blocked",
                            "reason": "path_extraction_failed",
                            "error": str(e),
                            "handler": self.name,
                        },
                    )
                return ToolCallReactionResult(
                    should_swallow=False,
                    metadata={
                        "decision": "extraction_error_fail_open",
                        "error": str(e),
                    },
                )

            if not paths:
                logger.warning(
                    f"No file paths found in tool call '{context.tool_name}' with arguments: {list(context.tool_arguments.keys())}"
                )
                if self._config.strict_mode:
                    self._blocked_count += 1
                    return ToolCallReactionResult(
                        should_swallow=True,
                        replacement_response=f"File operation blocked: No file paths found in tool call. Allowed folder: {project_root}",
                        metadata={
                            "decision": "blocked",
                            "reason": "no_paths_found",
                            "tool_name": context.tool_name,
                            "project_root": str(project_root),
                            "handler": self.name,
                        },
                    )
                return ToolCallReactionResult(
                    should_swallow=False, metadata={"decision": "no_paths_found"}
                )

            violating_paths = []
            invalid_path_errors = []

            for path_str in paths:
                try:
                    normalized_path = self._validator.normalize_path(
                        path_str, str(project_root)
                    )
                    if not self._validator.is_within_boundary(
                        normalized_path,
                        project_root,
                        allow_parent=self._config.allow_parent_access,
                    ):
                        violating_paths.append(path_str)
                except ValueError as e:
                    invalid_path_errors.append((path_str, str(e)))

            if violating_paths or invalid_path_errors:
                self._blocked_count += 1
                if invalid_path_errors:
                    self._validation_errors += len(invalid_path_errors)

                if self._config.strict_mode or violating_paths:
                    error_messages = []
                    if violating_paths:
                        error_messages.append(
                            f"Paths outside project root: {', '.join(violating_paths)}"
                        )
                    if invalid_path_errors:
                        error_messages.append(
                            f"Invalid paths: {', '.join([p for p, e in invalid_path_errors])}"
                        )

                    return ToolCallReactionResult(
                        should_swallow=True,
                        replacement_response=f"File operation blocked. {'. '.join(error_messages)}. Allowed folder: {project_root}",
                        metadata={
                            "decision": "blocked",
                            "reason": "path_validation_failed",
                            "tool_name": context.tool_name,
                            "violating_paths": violating_paths,
                            "invalid_path_errors": [
                                {"path": p, "error": e} for p, e in invalid_path_errors
                            ],
                            "project_root": str(project_root),
                            "handler": self.name,
                            "session_id": context.session_id,
                        },
                    )

            if invalid_path_errors:  # non-strict mode
                logger.warning(
                    f"Allowing tool call '{context.tool_name}' despite path validation errors (non-strict mode): {invalid_path_errors}"
                )

            logger.debug(
                f"Tool call '{context.tool_name}' validated successfully: all paths within project root '{project_root}'"
            )
            self._allowed_count += 1
            return ToolCallReactionResult(
                should_swallow=False, metadata={"decision": "allowed"}
            )

        except Exception as e:
            logger.error(
                f"Unexpected error in file sandboxing handler for tool '{context.tool_name}': {e}",
                exc_info=True,
            )
            return ToolCallReactionResult(
                should_swallow=False,
                metadata={"decision": "error_fail_open", "error": str(e)},
            )
