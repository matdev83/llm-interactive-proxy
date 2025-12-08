"""
Windows Double-Ampersand Command Fixer.

Provides automatic on-the-fly rewriting of && to ; in command execution
tool calls for Windows clients. Remote LLMs are trained on Linux workflows
and frequently generate shell commands using && as command separator, which
fails on Windows PowerShell.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to match && with optional surrounding whitespace
_DOUBLE_AMPERSAND_PATTERN = re.compile(r"\s*&&\s*")


class WindowsDoubleAmpersandFixer:
    """Service that fixes double-ampersand command separators for Windows clients."""

    COMMAND_EXECUTION_TOOLS: frozenset[str] = frozenset(
        {
            "execute",
            "run_command",
            "bash",
            "shell",
            "terminal",
            "exec",
            "run",
            "execute_command",
            "cmd",
            "powershell",
            "command",
            "run_terminal_command",
            "execute_bash",
            "run_shell",
            "run_in_terminal",
            "execute_shell",
            "shell_exec",
            "terminal_command",
        }
    )

    FILE_EDITING_TOOLS: frozenset[str] = frozenset(
        {
            "write_file",
            "edit",
            "create",
            "str_replace",
            "patch_file",
            "apply_diff",
            "multiedit",
            "insert_content",
            "replace_lines",
            "replace_in_file",
            "write_to_file",
            "fs_write_text_file",
            "fs/write_text_file",
            "patchfile",
            "strreplace",
            "multi_edit",
            "read",
            "read_file",
            "grep",
            "glob",
            "ls",
            "todowrite",
        }
    )

    def __init__(self, enabled: bool = True) -> None:
        """Initialize the fixer.

        Args:
            enabled: Whether the feature is enabled (default: True)
        """
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        """Whether the fixer is enabled."""
        return self._enabled

    def is_command_execution_tool(self, tool_name: str) -> bool:
        """Check if tool name matches a command execution tool.

        Args:
            tool_name: The name of the tool

        Returns:
            True if tool executes commands, False otherwise
        """
        if not tool_name:
            return False
        normalized = tool_name.lower().replace("-", "_").replace("/", "_")
        return normalized in self.COMMAND_EXECUTION_TOOLS

    def is_file_editing_tool(self, tool_name: str) -> bool:
        """Check if tool name matches a file editing tool.

        Args:
            tool_name: The name of the tool

        Returns:
            True if tool edits files, False otherwise
        """
        if not tool_name:
            return False
        normalized = tool_name.lower().replace("-", "_").replace("/", "_")
        return normalized in self.FILE_EDITING_TOOLS

    def is_windows_client(self, client_os: str | None) -> bool:
        """Check if the client OS is Windows.

        Args:
            client_os: The detected client OS string

        Returns:
            True if client is Windows, False otherwise
        """
        if not client_os:
            return False
        lower_os = client_os.lower()
        # Check for Windows indicators, but exclude "darwin" which contains "win"
        if "darwin" in lower_os:
            return False
        return "win" in lower_os or "windows" in lower_os

    def should_process(self, tool_name: str, client_os: str | None) -> bool:
        """Check if this tool call should be processed for && replacement.

        Args:
            tool_name: The name of the tool
            client_os: The detected client OS (from session state)

        Returns:
            True if tool call should be processed, False otherwise
        """
        if not self._enabled:
            return False

        if not self.is_windows_client(client_os):
            return False

        if self.is_file_editing_tool(tool_name):
            return False

        return self.is_command_execution_tool(tool_name)

    def fix_command_string(self, command: str) -> tuple[str, bool]:
        """Replace && with ; in a command string.

        Args:
            command: The command string to fix

        Returns:
            Tuple of (fixed_command, was_modified)
        """
        if not command or not isinstance(command, str):
            return command, False

        if "&&" not in command:
            return command, False

        fixed = _DOUBLE_AMPERSAND_PATTERN.sub(" ; ", command)
        return fixed, True

    def _extract_command_string(self, arguments: Any) -> tuple[str | None, str | None]:
        """Extract a shell command string from tool arguments.

        Supports:
        - Raw string
        - JSON string -> dict extraction
        - Dict with common keys: 'command', 'cmd'

        Args:
            arguments: The tool arguments

        Returns:
            Tuple of (command_string, key_used) where key_used is the dict key
            that contained the command, or None for raw string arguments.
        """
        if arguments is None:
            return None, None

        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                arguments = parsed
            except json.JSONDecodeError:
                return arguments, None

        if isinstance(arguments, dict):
            for key in ("command", "cmd", "script", "shell_command"):
                cmd = arguments.get(key)
                if isinstance(cmd, str) and cmd.strip():
                    return cmd, key

            for outer_key in ("input", "body", "data"):
                inner = arguments.get(outer_key)
                if isinstance(inner, dict):
                    for key in ("command", "cmd"):
                        sub = inner.get(key)
                        if isinstance(sub, str) and sub.strip():
                            return sub, f"{outer_key}.{key}"

        return None, None

    def fix_tool_arguments(
        self,
        tool_arguments: Any,
        tool_name: str,
        client_os: str | None,
    ) -> tuple[Any, bool]:
        """Fix double-ampersands in tool arguments if applicable.

        Args:
            tool_arguments: The tool arguments (dict, str, or other)
            tool_name: The name of the tool
            client_os: The detected client OS

        Returns:
            Tuple of (possibly_modified_arguments, was_modified)
        """
        if not self.should_process(tool_name, client_os):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping double-ampersand fix: tool=%s, client_os=%s, "
                    "is_cmd_tool=%s, is_file_tool=%s, is_windows=%s",
                    tool_name,
                    client_os,
                    self.is_command_execution_tool(tool_name),
                    self.is_file_editing_tool(tool_name),
                    self.is_windows_client(client_os),
                )
            return tool_arguments, False

        command_str, key_path = self._extract_command_string(tool_arguments)
        if not command_str:
            return tool_arguments, False

        fixed_command, was_modified = self.fix_command_string(command_str)
        if not was_modified:
            return tool_arguments, False

        if logger.isEnabledFor(logging.INFO):
            orig_preview = (
                command_str[:200] + "..." if len(command_str) > 200 else command_str
            )
            fixed_preview = (
                fixed_command[:200] + "..."
                if len(fixed_command) > 200
                else fixed_command
            )
            logger.info(
                "Fixed double-ampersand in command for Windows client: "
                "tool=%s, original='%s', fixed='%s'",
                tool_name,
                orig_preview,
                fixed_preview,
            )

        if key_path is None:
            return fixed_command, True

        if isinstance(tool_arguments, str):
            try:
                parsed = json.loads(tool_arguments)
                if isinstance(parsed, dict):
                    self._set_nested_value(parsed, key_path, fixed_command)
                    return json.dumps(parsed), True
            except json.JSONDecodeError:
                return fixed_command, True

        if isinstance(tool_arguments, dict):
            result = dict(tool_arguments)
            self._set_nested_value(result, key_path, fixed_command)
            return result, True

        return tool_arguments, False

    @staticmethod
    def _set_nested_value(d: dict[str, Any], key_path: str, value: Any) -> None:
        """Set a value in a nested dict using a dot-separated key path."""
        keys = key_path.split(".")
        current = d
        for key in keys[:-1]:
            if key in current and isinstance(current[key], dict):
                current = current[key]
            else:
                return
        if keys[-1] in current:
            current[keys[-1]] = value
