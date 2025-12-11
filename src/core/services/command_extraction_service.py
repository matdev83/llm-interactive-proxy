"""
Shared Command Extraction Service.

This module provides common utilities for extracting and normalizing
command strings from tool call arguments, used by both dangerous command
detection and file sandboxing features.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CommandExtractionService:
    """Service for extracting and normalizing commands from tool call arguments.

    This service consolidates duplicated logic from DangerousCommandService
    and FileSandboxingHandler into a single, reusable component.
    """

    # Common shell tool patterns (compiled for performance)
    _SHELL_TOOL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
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
    )

    # Pattern to strip common environment variable prefixes
    _ENV_PREFIX_PATTERN = re.compile(
        r"^\s*(?:(?:[A-Z_][A-Z0-9_]*=[^\s]*\s+)+)?(.*)$",
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern to extract subshell contents
    _SUBSHELL_PATTERN = re.compile(r"\$\([^)]+\)")

    def __init__(self, max_command_length: int = 10000) -> None:
        """Initialize the command extraction service.

        Args:
            max_command_length: Maximum command length to process (for performance).
        """
        self._max_command_length = max_command_length

    def is_shell_tool(self, tool_name: str) -> bool:
        """Check if a tool name matches shell/command execution patterns.

        Args:
            tool_name: The name of the tool to check.

        Returns:
            True if the tool is a shell/command execution tool.
        """
        return any(pattern.search(tool_name) for pattern in self._SHELL_TOOL_PATTERNS)

    def is_shell_tool_by_name(
        self, tool_name: str, tool_names: set[str] | list[str]
    ) -> bool:
        """Check if a tool name matches a configured list of shell tool names.

        Args:
            tool_name: The name of the tool to check.
            tool_names: Set or list of tool names to match against.

        Returns:
            True if the tool name matches (case-insensitive).
        """
        normalized = tool_name.lower()
        if isinstance(tool_names, set):
            return normalized in tool_names
        return normalized in {n.lower() for n in tool_names}

    def extract_command_string(self, arguments: Any) -> str | None:
        """Extract command string from tool call arguments.

        Handles various argument formats:
        - Raw string
        - JSON string containing command
        - Dictionary with command/cmd key
        - Nested structures

        Args:
            arguments: The tool call arguments in any format.

        Returns:
            Extracted command string, or None if not found.
        """
        if arguments is None:
            return None

        # Handle raw string
        if isinstance(arguments, str):
            # Try parsing as JSON first
            try:
                parsed = json.loads(arguments)
                return self._extract_from_dict(parsed)
            except (json.JSONDecodeError, TypeError):
                # Treat as raw command if not valid JSON
                if arguments.strip():
                    return self._truncate(arguments.strip())
                return None

        # Handle dictionary
        if isinstance(arguments, dict):
            return self._extract_from_dict(arguments)

        # Handle list (join elements)
        if isinstance(arguments, list):
            with contextlib.suppress(Exception):
                joined = " ".join(str(part) for part in arguments)
                if joined.strip():
                    return self._truncate(joined.strip())

        return None

    def extract_command_strings(self, arguments: dict[str, object]) -> list[str]:
        """Extract all command strings from tool arguments.

        This method extracts from multiple common parameter names.

        Args:
            arguments: Tool call arguments dictionary.

        Returns:
            List of extracted command strings.
        """
        if not isinstance(arguments, dict):
            return []

        strings: list[str] = []

        # Check common command keys
        for key in ("command", "cmd", "script", "code"):
            cmd = arguments.get(key)
            if isinstance(cmd, str) and cmd.strip():
                strings.append(self._truncate(cmd.strip()))
            elif isinstance(cmd, list):
                with contextlib.suppress(Exception):
                    joined = " ".join(str(part) for part in cmd)
                    if joined.strip():
                        strings.append(self._truncate(joined))

        # Also check args list
        args_val = arguments.get("args")
        if isinstance(args_val, list):
            with contextlib.suppress(Exception):
                joined = " ".join(str(part) for part in args_val)
                if joined.strip():
                    strings.append(self._truncate(joined))

        return strings

    def normalize_command(self, command: str) -> str:
        """Normalize a command string for pattern matching.

        Performs the following normalizations:
        - Collapse whitespace
        - Strip environment variable prefixes
        - Expand subshell invocations

        Args:
            command: Raw command string.

        Returns:
            Normalized command string.
        """
        if not command:
            return ""

        normalized = command

        # Collapse whitespace
        normalized = " ".join(normalized.split())

        # Strip environment prefix
        match = self._ENV_PREFIX_PATTERN.match(normalized)
        if match:
            normalized = match.group(1)

        # Handle subshell patterns like $(which git)
        normalized = self._SUBSHELL_PATTERN.sub("cmd", normalized)

        return normalized.strip()

    def extract_paths_from_command(
        self, command: str, project_root: Path | None = None
    ) -> list[str]:
        """Extract file/directory paths referenced in a shell command.

        Args:
            command: Shell command string.
            project_root: Optional project root for path normalization.

        Returns:
            List of path strings found in the command.
        """
        if not command:
            return []

        path_candidates: set[str] = set()

        # Patterns for destructive commands with paths
        patterns = [
            re.compile(r"\bcd\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
            re.compile(r"\bpushd\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
            re.compile(
                r"\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+(?P<path>[^\s;&]+)", re.IGNORECASE
            ),
            re.compile(r"\bfind\s+(?P<start>[^\s;&]+)[^\n;&]*?-delete", re.IGNORECASE),
            re.compile(
                r"\bfind\s+(?P<start>[^\s;&]+)[^\n;&]*?-exec\s+rm\s+-[^\s]*r[^\s]*f[^\s]*\s+(?P<path>[^\s;&]+)",
                re.IGNORECASE,
            ),
            re.compile(r"\b(?:rmdir|rd)\s+/s\s+/q\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
            re.compile(r"\bdel\s+/s\s+/q\s+(?P<path>[^\s;&]+)", re.IGNORECASE),
            re.compile(
                r"\bRemove-Item\s+(?P<path>[^\s;&]+)[^\n;&]*-Recurse", re.IGNORECASE
            ),
        ]

        # Fallback pattern for absolute paths
        # On Windows: match drive letters with single backslash (C:\...) OR UNC paths
        # (\\server\...). We don't match Unix-style / paths on Windows since they may
        # incorrectly catch relative paths like ./.venv/... that get misinterpreted.
        absolute_path_fallback = re.compile(r"(?P<path>(?:[A-Za-z]:|\\\\)[^\s'\";]+)")

        for pattern in patterns:
            for match in pattern.finditer(command):
                for group_name in ("path", "start"):
                    candidate = match.groupdict().get(group_name)
                    if candidate:
                        path_candidates.add(candidate)

        for match in absolute_path_fallback.finditer(command):
            candidate = match.group("path")
            if candidate:
                path_candidates.add(candidate)

        return list(path_candidates)

    def _extract_from_dict(self, data: dict[str, Any]) -> str | None:
        """Extract command from a dictionary structure."""
        # Check common command keys
        for key in ("command", "cmd", "script", "code"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return self._truncate(value.strip())
            if isinstance(value, list):
                with contextlib.suppress(Exception):
                    joined = " ".join(str(part) for part in value)
                    if joined.strip():
                        return self._truncate(joined)

        # Check nested input structure
        input_val = data.get("input")
        if isinstance(input_val, dict):
            return self._extract_from_dict(input_val)
        if isinstance(input_val, str) and input_val.strip():
            return self._truncate(input_val.strip())

        # Check args list
        args_val = data.get("args")
        if isinstance(args_val, list):
            with contextlib.suppress(Exception):
                joined = " ".join(str(part) for part in args_val)
                if joined.strip():
                    return self._truncate(joined)

        return None

    def _truncate(self, command: str) -> str:
        """Truncate command to max length."""
        if len(command) > self._max_command_length:
            return command[: self._max_command_length]
        return command
