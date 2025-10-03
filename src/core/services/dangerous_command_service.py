import json
from typing import Any

from src.core.domain.chat import ToolCall
from src.core.domain.configuration.dangerous_command_config import (
    DangerousCommandConfig,
    DangerousCommandRule,
)


class DangerousCommandService:
    def __init__(self, config: DangerousCommandConfig):
        self.config = config

    def scan_tool_call(
        self, tool_call: ToolCall
    ) -> tuple[DangerousCommandRule, str] | None:
        """
        Scans a tool call for dangerous commands.

        Args:
            tool_call: The tool call to scan.

        Returns:
            A tuple containing the matched rule and the command string if a dangerous
            command is found, otherwise None.
        """
        return self.scan(tool_call.function.name, tool_call.function.arguments)

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
                parsed = json.loads(arguments)
                arguments = parsed
            except json.JSONDecodeError:
                # Plain string
                s: str = arguments
                return s

        # If dict, try common fields
        if isinstance(arguments, dict):
            cmd = arguments.get("command") or arguments.get("cmd")
            if isinstance(cmd, str) and cmd.strip():
                return cmd
            # Sometimes a sub-dict holds the command
            for key in ("input", "body", "data"):
                inner = arguments.get(key)
                if isinstance(inner, dict):
                    sub = inner.get("command") or inner.get("cmd")
                    if isinstance(sub, str) and sub.strip():
                        return sub
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

    def scan(
        self, tool_name: str, arguments: Any
    ) -> tuple[DangerousCommandRule, str] | None:
        """Scan tool_name and arguments for dangerous command.

        Returns matched rule and reconstructed command string, or None.
        """
        if tool_name not in self.config.tool_names:
            return None

        command_to_check = self._extract_command_string(arguments)
        if not command_to_check:
            return None

        for rule in self.config.rules:
            if rule.pattern.search(command_to_check):
                return rule, command_to_check
        return None
