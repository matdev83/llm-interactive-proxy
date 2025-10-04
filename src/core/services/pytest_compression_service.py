import logging
import re
from typing import Any

from src.core.domain.chat import ToolCall

logger = logging.getLogger(__name__)


class PytestCompressionService:
    """Service to detect pytest commands in tool calls and set compression state."""

    def __init__(self) -> None:
        # Tool names that execute shell commands
        self.shell_tool_names = [
            "bash",
            "exec_command",
            "execute_command",
            "run_shell_command",
            "shell",
            "local_shell",
            "container.exec",
        ]

        # Pattern to detect pytest in command arguments (supports pytest and py.test aliases)
        self.pytest_pattern = re.compile(r"\bpy\.?test\b", re.IGNORECASE)

    def scan_tool_call_for_pytest(self, tool_call: ToolCall) -> tuple[bool, str] | None:
        """
        Scans a tool call for pytest commands.

        Args:
            tool_call: The tool call to scan.

        Returns:
            A tuple containing (True, command_string) if pytest is detected,
            otherwise None.
        """
        return self.scan_for_pytest(
            tool_call.function.name, tool_call.function.arguments
        )

    def _normalize_command_value(self, value: Any) -> str | None:
        """Normalize command values to a single string.

        Handles strings directly as well as list/tuple command representations
        that are common when shell execution helpers pass structured arguments.
        Returns ``None`` for unsupported types or when conversion fails.
        """

        if value is None:
            return None

        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None

        if isinstance(value, list | tuple):
            try:
                parts = [str(part).strip() for part in value if part is not None]
            except Exception:
                return None

            joined = " ".join(part for part in parts if part)
            return joined or None

        return None

    def _extract_command_string(self, arguments: Any) -> str | None:
        """Extract a shell command string from tool arguments.

        Supports:
        - Raw string
        - JSON string -> dict extraction
        - Dict with common keys: 'command', 'cmd'
        - Dict 'args' list joined to string
        """
        if arguments is None:
            return None

        # If it's already a string, see if it's JSON first
        if isinstance(arguments, str):
            try:
                import json

                parsed = json.loads(arguments)
                arguments = parsed
            except (ValueError, TypeError):
                # Plain string
                s: str = arguments
                return s

        # If dict, try common fields
        if isinstance(arguments, dict):
            cmd_value = arguments.get("command")
            if cmd_value is None:
                cmd_value = arguments.get("cmd")

            normalized_cmd = self._normalize_command_value(cmd_value)
            if normalized_cmd:
                return normalized_cmd
            # Sometimes a sub-dict holds the command
            for key in ("input", "body", "data"):
                inner = arguments.get(key)
                if isinstance(inner, dict):
                    sub_value = inner.get("command")
                    if sub_value is None:
                        sub_value = inner.get("cmd")
                    normalized_sub = self._normalize_command_value(sub_value)
                    if normalized_sub:
                        return normalized_sub
            # If args array provided, join into a single string
            args = arguments.get("args")
            if isinstance(args, list) and args:
                try:
                    return " ".join(str(a) for a in args)
                except Exception:
                    return None
            return None

        # If list, join
        if isinstance(arguments, list):
            try:
                return " ".join(str(a) for a in arguments)
            except Exception:
                return None
        return None

    def scan_for_pytest(
        self, tool_name: str, arguments: Any
    ) -> tuple[bool, str] | None:
        """
        Scan tool_name and arguments for pytest command.

        Returns (True, command_string) if pytest is detected, otherwise None.
        """
        # Only scan shell execution tools
        if tool_name not in self.shell_tool_names:
            return None

        command_to_check = self._extract_command_string(arguments)
        if not command_to_check:
            return None

        # Check if command contains pytest
        if self.pytest_pattern.search(command_to_check):
            logger.info(
                f"Detected pytest command in tool call '{tool_name}': {command_to_check}"
            )
            return True, command_to_check

        return None
