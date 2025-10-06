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
            cmd = arguments.get("command") or arguments.get("cmd")
            cmd_str = self._stringify_command_value(cmd)
            if cmd_str:
                return cmd_str
            # Sometimes a sub-dict holds the command
            for key in ("input", "body", "data"):
                inner = arguments.get(key)
                if isinstance(inner, dict):
                    sub = inner.get("command") or inner.get("cmd")
                    sub_str = self._stringify_command_value(sub)
                    if sub_str:
                        return sub_str
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

    def _stringify_command_value(self, value: Any) -> str | None:
        """Convert a command value to a shell string if possible."""

        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list | tuple):
            parts = []
            for item in value:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    parts.append(text)
            if parts:
                return " ".join(parts)
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
