"""
Unit tests for WindowsDoubleAmpersandFixer service.
"""

from __future__ import annotations

import json

import pytest
from src.core.services.windows_double_ampersand_fixer import (
    CommandFixResult,
    WindowsDoubleAmpersandFixer,
)


class TestIsCommandExecutionTool:
    """Tests for is_command_execution_tool method."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    @pytest.mark.parametrize(
        "tool_name",
        [
            "execute",
            "Execute",
            "EXECUTE",
            "run_command",
            "Run_Command",
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
            "run-command",
            "execute-command",
        ],
    )
    def test_recognizes_command_execution_tools(
        self, fixer: WindowsDoubleAmpersandFixer, tool_name: str
    ) -> None:
        assert fixer.is_command_execution_tool(tool_name) is True

    @pytest.mark.parametrize(
        "tool_name",
        [
            "write_file",
            "Edit",
            "Create",
            "str_replace",
            "patch_file",
            "apply_diff",
            "read_file",
            "grep",
            "unknown_tool",
            "",
        ],
    )
    def test_rejects_non_command_tools(
        self, fixer: WindowsDoubleAmpersandFixer, tool_name: str
    ) -> None:
        assert fixer.is_command_execution_tool(tool_name) is False


class TestIsFileEditingTool:
    """Tests for is_file_editing_tool method."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    @pytest.mark.parametrize(
        "tool_name",
        [
            "write_file",
            "Write_File",
            "edit",
            "Edit",
            "create",
            "Create",
            "str_replace",
            "patch_file",
            "apply_diff",
            "multiedit",
            "insert_content",
            "replace_lines",
            "read",
            "read_file",
            "grep",
            "glob",
            "ls",
        ],
    )
    def test_recognizes_file_editing_tools(
        self, fixer: WindowsDoubleAmpersandFixer, tool_name: str
    ) -> None:
        assert fixer.is_file_editing_tool(tool_name) is True

    @pytest.mark.parametrize(
        "tool_name",
        [
            "execute",
            "run_command",
            "bash",
            "unknown_tool",
            "",
        ],
    )
    def test_rejects_non_file_tools(
        self, fixer: WindowsDoubleAmpersandFixer, tool_name: str
    ) -> None:
        assert fixer.is_file_editing_tool(tool_name) is False


class TestIsWindowsClient:
    """Tests for is_windows_client method."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    @pytest.mark.parametrize(
        "client_os",
        [
            "win32",
            "Win32",
            "WIN32",
            "windows",
            "Windows",
            "Windows 10",
            "win32 10.0.19045",
            "Windows NT",
        ],
    )
    def test_recognizes_windows(
        self, fixer: WindowsDoubleAmpersandFixer, client_os: str
    ) -> None:
        assert fixer.is_windows_client(client_os) is True

    @pytest.mark.parametrize(
        "client_os",
        [
            "linux",
            "Linux",
            "darwin",
            "Darwin",
            "macos",
            "MacOS",
            "",
            None,
        ],
    )
    def test_rejects_non_windows(
        self, fixer: WindowsDoubleAmpersandFixer, client_os: str | None
    ) -> None:
        assert fixer.is_windows_client(client_os) is False


class TestShouldProcess:
    """Tests for should_process method."""

    def test_returns_false_when_disabled(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=False)
        assert fixer.should_process("execute", "win32") is False

    def test_returns_false_for_non_windows(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        assert fixer.should_process("execute", "linux") is False
        assert fixer.should_process("execute", None) is False

    def test_returns_false_for_file_editing_tools(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        assert fixer.should_process("write_file", "win32") is False
        assert fixer.should_process("Edit", "win32") is False

    def test_returns_true_for_command_tools_on_windows(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        assert fixer.should_process("execute", "win32") is True
        assert fixer.should_process("run_command", "Windows") is True
        assert fixer.should_process("bash", "win32 10.0.19045") is True

    def test_returns_false_for_unknown_tools(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=True)
        assert fixer.should_process("unknown_tool", "win32") is False


class TestFixCommandString:
    """Tests for fix_command_string method."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    def test_replaces_single_double_ampersand(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        result = fixer.fix_command_string("echo test1 && echo test2")
        assert result.was_modified is True
        assert result.fixed_command == "echo test1 ; echo test2"

    def test_replaces_multiple_double_ampersands(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        result = fixer.fix_command_string("cmd1 && cmd2 && cmd3 && cmd4")
        assert result.was_modified is True
        assert result.fixed_command == "cmd1 ; cmd2 ; cmd3 ; cmd4"

    def test_handles_no_space_around_ampersands(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        result = fixer.fix_command_string("cmd1&&cmd2")
        assert result.was_modified is True
        assert result.fixed_command == "cmd1 ; cmd2"

    def test_handles_extra_spaces(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        result = fixer.fix_command_string("cmd1  &&  cmd2")
        assert result.was_modified is True
        assert result.fixed_command == "cmd1 ; cmd2"

    def test_no_modification_without_double_ampersand(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        result = fixer.fix_command_string("echo test")
        assert result.was_modified is False
        assert result.fixed_command == "echo test"

    def test_no_modification_for_single_ampersand(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        result = fixer.fix_command_string("cmd1 & cmd2")
        assert result.was_modified is False
        assert result.fixed_command == "cmd1 & cmd2"

    def test_handles_empty_string(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        result = fixer.fix_command_string("")
        assert result.was_modified is False
        assert result.fixed_command == ""

    def test_handles_none(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        result = fixer.fix_command_string(None)  # type: ignore[arg-type]
        assert result.was_modified is False
        assert result.fixed_command is None

    def test_handles_triple_ampersand(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        result = fixer.fix_command_string("cmd1 &&& cmd2")
        assert result.was_modified is True
        assert ";" in result.fixed_command
        assert "&" in result.fixed_command


class TestFixToolArguments:
    """Tests for fix_tool_arguments method."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    def test_fixes_dict_with_command_key(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = {"command": "echo test1 && echo test2"}
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert isinstance(result, CommandFixResult)
        assert result.was_modified is True
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test1 ; echo test2"

    def test_fixes_dict_with_cmd_key(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        args = {"cmd": "echo test1 && echo test2"}
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert result.was_modified is True
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["cmd"] == "echo test1 ; echo test2"

    def test_fixes_raw_string_argument(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = "echo test1 && echo test2"
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert isinstance(result, CommandFixResult)
        assert result.was_modified is True
        assert result.fixed_command == "echo test1 ; echo test2"

    def test_fixes_json_string_argument(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = json.dumps({"command": "echo test1 && echo test2"})
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert isinstance(result, CommandFixResult)
        assert isinstance(result.fixed_command, str)
        assert result.was_modified is True
        parsed = json.loads(result.fixed_command)
        assert parsed["command"] == "echo test1 ; echo test2"

    def test_skips_file_editing_tools(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        args = {"command": "echo test1 && echo test2"}
        result = fixer.fix_tool_arguments(args, "write_file", "win32")
        assert result.was_modified is False
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test1 && echo test2"

    def test_skips_non_windows_clients(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = {"command": "echo test1 && echo test2"}
        result = fixer.fix_tool_arguments(args, "execute", "linux")
        assert result.was_modified is False
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test1 && echo test2"

    def test_skips_when_disabled(self) -> None:
        fixer = WindowsDoubleAmpersandFixer(enabled=False)
        args = {"command": "echo test1 && echo test2"}
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert result.was_modified is False
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test1 && echo test2"

    def test_no_modification_without_double_ampersand(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = {"command": "echo test"}
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert result.was_modified is False
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test"

    def test_handles_nested_dict(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        args = {"input": {"command": "echo test1 && echo test2"}}
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert result.was_modified is True
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        inner = fixed["input"]
        assert isinstance(inner, dict)
        assert inner["command"] == "echo test1 ; echo test2"

    def test_preserves_other_keys(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        args = {
            "command": "echo test1 && echo test2",
            "timeout": 60,
            "cwd": "/home/user",
        }
        result = fixer.fix_tool_arguments(args, "execute", "win32")
        assert result.was_modified is True
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test1 ; echo test2"
        assert fixed["timeout"] == 60
        assert fixed["cwd"] == "/home/user"


class TestEdgeCases:
    """Tests for edge cases and safety."""

    @pytest.fixture
    def fixer(self) -> WindowsDoubleAmpersandFixer:
        return WindowsDoubleAmpersandFixer(enabled=True)

    def test_very_long_command(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        long_cmd = " && ".join([f"cmd{i}" for i in range(1000)])
        result = fixer.fix_command_string(long_cmd)
        assert result.was_modified is True
        assert "&&" not in result.fixed_command
        assert " ; " in result.fixed_command

    def test_command_with_ampersand_in_quotes(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        cmd = 'echo "test && value" && echo done'
        result = fixer.fix_command_string(cmd)
        assert result.was_modified is True
        assert " ; " in result.fixed_command

    def test_whitespace_only_command(self, fixer: WindowsDoubleAmpersandFixer) -> None:
        result = fixer.fix_command_string("   ")
        assert result.was_modified is False
        assert result.fixed_command == "   "

    def test_case_insensitive_tool_matching(
        self, fixer: WindowsDoubleAmpersandFixer
    ) -> None:
        args = {"command": "echo test && echo done"}
        result = fixer.fix_tool_arguments(args, "EXECUTE", "WIN32")
        assert result.was_modified is True
        fixed = result.fixed_command
        assert isinstance(fixed, dict)
        assert fixed["command"] == "echo test ; echo done"
