"""File sandboxing handler for tool call reactor system.

This module implements the FileSandboxingHandler that intercepts file-changing
tool calls and validates that they operate within the project directory boundary.
"""

from __future__ import annotations

import contextlib
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

# Pre-compiled regex patterns for path extraction (performance optimization)
# Module-level constants avoid recompiling on every _extract_paths_from_command_strings call
_PATH_EXTRACTION_PATTERNS = (
    re.compile(r"\bcd\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
    re.compile(r"\bpushd\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
    re.compile(r"\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
    re.compile(r"\bfind\s+(?P<start>[^\s;&]+)[^\n;&]*?-delete", re.IGNORECASE),
    re.compile(
        r"\bfind\s+(?P<start>[^\s;&]+)[^\n;&]*?-exec\s+rm\s+-[^\s]*r[^\s]*f[^\s]*\s+(?P<path>[^\s;&]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:rmdir|rd)\s+/s\s+/q\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
    re.compile(r"\bdel\s+/s\s+/q\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
    re.compile(r"\bRemove-Item\s+(?P<path>[^\s;&]+)[^\n;&]*-Recurse", re.IGNORECASE),
)

_ABSOLUTE_PATH_FALLBACK_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:\\|/|\\)[^\s'\";]+)"
)


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
        self._shell_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in [
                r"\bexecute\b",
                r"execute_command",
                r"run_shell_command",
                r"run_terminal_command",
                r"exec_command",
                r"\bshell\b",
                r"\bbash\b",
                r"local_shell",
                r"container\.exec",
            ]
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
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Tool '{tool_name}' is excluded from sandboxing")
                return False

        # Check if tool matches file-changing patterns
        return any(pattern.search(tool_name) for pattern in self._tool_patterns)

    def _is_shell_tool(self, tool_name: str) -> bool:
        return any(pattern.search(tool_name) for pattern in self._shell_patterns)

    def _extract_command_strings(self, arguments: dict[str, object]) -> list[str]:
        """Pull raw command strings out of common command tool args."""
        cmd = arguments.get("command") or arguments.get("cmd")
        strings: list[str] = []

        if isinstance(cmd, str) and cmd.strip():
            strings.append(cmd)
        elif isinstance(cmd, list):
            with contextlib.suppress(Exception):
                strings.append(" ".join(str(part) for part in cmd))

        # Also inspect args list for stringified commands
        args_val = arguments.get("args")
        if isinstance(args_val, list):
            with contextlib.suppress(Exception):
                joined = " ".join(str(part) for part in args_val)
                if joined.strip():
                    strings.append(joined)

        return strings

    def _extract_paths_from_command_strings(
        self, commands: list[str], project_root: Path
    ) -> list[str]:
        """Extract candidate paths referenced in shell commands."""
        if not commands:
            return []

        path_candidates: set[str] = set()

        for command in commands:
            # Use module-level pre-compiled patterns
            for pattern in _PATH_EXTRACTION_PATTERNS:
                for match in pattern.finditer(command):
                    for group_name in ("path", "start"):
                        candidate = match.groupdict().get(group_name)
                        if candidate:
                            path_candidates.add(candidate)

            for match in _ABSOLUTE_PATH_FALLBACK_PATTERN.finditer(command):
                candidate = match.group("path")
                if candidate:
                    path_candidates.add(candidate)

        # Filter out candidates that normalize inside project_root to avoid blocking benign relative paths.
        results: list[str] = []
        for candidate in path_candidates:
            try:
                normalized = self._validator.normalize_path(
                    candidate, str(project_root)
                )
                if not self._validator.is_within_boundary(
                    normalized,
                    project_root,
                    allow_parent=self._config.allow_parent_access,
                ):
                    results.append(candidate)
            except ValueError:
                # If it fails to normalize, leave to main handler to decide strictness
                results.append(candidate)

        return results

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
                if logger.isEnabledFor(logging.DEBUG):
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
                # For shell-like tools, fall back to parsing command strings for destructive paths
                if self._is_shell_tool(context.tool_name):
                    commands = self._extract_command_strings(context.tool_arguments)
                    paths = self._extract_paths_from_command_strings(
                        commands, project_root
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
                            f"Invalid paths: {', '.join([p for p, _ in invalid_path_errors])}"
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

            if logger.isEnabledFor(logging.DEBUG):
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
