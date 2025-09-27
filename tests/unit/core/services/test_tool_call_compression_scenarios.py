#!/usr/bin/env python3
"""
Comprehensive tests for tool call compression scenarios.

This test module verifies the critical requirement: pytest compression should only
be applied to replies to tool calls containing pytest output, not to the tool calls
themselves or other subsequent messages.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import json
from unittest.mock import patch

import pytest
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
from src.core.services.response_manager_service import AgentResponseFormatter


class TestToolCallCompressionScenarios:
    """Test pytest compression behavior in tool call scenarios."""

    @pytest.fixture
    def formatter(self):
        """Create an AgentResponseFormatter for testing."""
        return AgentResponseFormatter()

    @pytest.fixture
    def session_with_compression_enabled(self):
        """Create a session with pytest compression enabled."""
        return Session(
            session_id="test-session",
            state=SessionState(pytest_compression_enabled=True),
            agent="cline",
        )

    @pytest.fixture
    def session_with_compression_disabled(self):
        """Create a session with pytest compression disabled."""
        return Session(
            session_id="test-session",
            state=SessionState(pytest_compression_enabled=False),
            agent="cline",
        )

    @pytest.fixture
    def sample_pytest_output(self):
        """Sample pytest output for testing."""
        return """============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-8.3.3, pluggy-1.5.0
collected 3 items

test_example.py::test_success PASSED                                       [ 33%]
test_example.py::test_failure FAILED                                       [ 66%]
test_example.py::test_another PASSED                                      [100%]

=================================== FAILURES ===================================
___________________________ test_failure ___________________________

    def test_failure():
>       assert False
E       AssertionError: assert False

test_example.py:6: AssertionError
=========================== short test summary info ============================
FAILED test_example.py::test_failure - AssertionError: assert False
========================= 1 failed, 2 passed in 0.12s ========================="""

    @pytest.fixture
    def sample_regular_output(self):
        """Sample regular (non-pytest) output for testing."""
        return "This is a regular command output that should not be compressed."

    def test_tool_call_pytest_compression_enabled(
        self, formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test that tool calls with pytest output are compressed when enabled."""
        # This simulates a tool call result from a shell execution
        tool_call_result = CommandResult(
            name="shell", message=sample_pytest_output, success=False  # Shell tool name
        )

        result = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_enabled
        )

        # Extract the compressed message from the tool call response
        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        compressed_message = args.get("result", "")

        # Verify compression was applied
        assert len(compressed_message) < len(sample_pytest_output)
        assert "PASSED" not in compressed_message  # Should be filtered out
        assert "FAILED" in compressed_message  # Should be preserved
        assert "AssertionError" in compressed_message  # Should be preserved

    def test_tool_call_pytest_compression_disabled(
        self, formatter, session_with_compression_disabled, sample_pytest_output
    ):
        """Test that tool calls with pytest output are not compressed when disabled."""
        tool_call_result = CommandResult(
            name="shell", message=sample_pytest_output, success=False
        )

        result = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_disabled
        )

        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        message = args.get("result", "")

        # Verify no compression was applied
        assert len(message) == len(sample_pytest_output)
        assert message == sample_pytest_output

    def test_tool_call_regular_output_no_compression(
        self, formatter, session_with_compression_enabled, sample_regular_output
    ):
        """Test that tool calls with regular output are not compressed."""
        tool_call_result = CommandResult(
            name="shell", message=sample_regular_output, success=True
        )

        result = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_enabled
        )

        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        message = args.get("result", "")

        # Verify no compression was applied
        assert len(message) == len(sample_regular_output)
        assert message == sample_regular_output

    def test_regular_command_pytest_compression(
        self, formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test that regular pytest commands (not tool calls) are still compressed."""
        # This simulates a direct pytest command execution
        regular_result = CommandResult(
            name="pytest",  # Direct pytest command
            message=sample_pytest_output,
            success=False,
        )

        result = formatter.format_command_result_for_agent(
            regular_result, session_with_compression_enabled
        )

        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        compressed_message = args.get("result", "")

        # Verify compression was applied
        assert len(compressed_message) < len(sample_pytest_output)
        assert "PASSED" not in compressed_message
        assert "FAILED" in compressed_message

    def test_compression_sequence_behavior(
        self,
        formatter,
        session_with_compression_enabled,
        sample_pytest_output,
        sample_regular_output,
    ):
        """Test the critical sequence: non-compressed -> compressed -> non-compressed."""

        # Step 1: Regular message (should NOT be compressed)
        regular_result = CommandResult(
            name="echo", message=sample_regular_output, success=True
        )

        result1 = formatter.format_command_result_for_agent(
            regular_result, session_with_compression_enabled
        )

        tool_call1 = result1["choices"][0]["message"]["tool_calls"][0]
        args1 = json.loads(tool_call1["function"]["arguments"])
        message1 = args1.get("result", "")

        # Verify step 1: No compression
        assert len(message1) == len(sample_regular_output)
        assert message1 == sample_regular_output

        # Step 2: Tool call with pytest output (SHOULD be compressed)
        tool_call_result = CommandResult(
            name="shell", message=sample_pytest_output, success=False
        )

        result2 = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_enabled
        )

        tool_call2 = result2["choices"][0]["message"]["tool_calls"][0]
        args2 = json.loads(tool_call2["function"]["arguments"])
        message2 = args2.get("result", "")

        # Verify step 2: Compression applied
        assert len(message2) < len(sample_pytest_output)
        assert "PASSED" not in message2

        # Step 3: Subsequent regular message (should NOT be compressed)
        subsequent_result = CommandResult(
            name="ls", message="Directory listing:\nfile1.txt\nfile2.py", success=True
        )

        result3 = formatter.format_command_result_for_agent(
            subsequent_result, session_with_compression_enabled
        )

        tool_call3 = result3["choices"][0]["message"]["tool_calls"][0]
        args3 = json.loads(tool_call3["function"]["arguments"])
        message3 = args3.get("result", "")

        # Verify step 3: No compression (back to normal)
        assert "Directory listing:" in message3
        assert "file1.txt" in message3
        assert "file2.py" in message3
        assert len(message3) == len("Directory listing:\nfile1.txt\nfile2.py")

    def test_different_shell_tool_names(
        self, formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test that all shell tool names are recognized for pytest compression."""
        shell_tool_names = [
            "bash",
            "exec_command",
            "execute_command",
            "run_shell_command",
            "shell",
            "local_shell",
            "container.exec",
        ]

        for tool_name in shell_tool_names:
            tool_call_result = CommandResult(
                name=tool_name, message=sample_pytest_output, success=False
            )

            result = formatter.format_command_result_for_agent(
                tool_call_result, session_with_compression_enabled
            )

            tool_call = result["choices"][0]["message"]["tool_calls"][0]
            args = json.loads(tool_call["function"]["arguments"])
            compressed_message = args.get("result", "")

            # Verify compression was applied for each shell tool
            assert len(compressed_message) < len(sample_pytest_output)
            assert "PASSED" not in compressed_message

    def test_command_extraction_logging(
        self, formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test that command extraction is properly logged."""
        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            tool_call_result = CommandResult(
                name="shell", message=sample_pytest_output, success=False
            )

            formatter.format_command_result_for_agent(
                tool_call_result, session_with_compression_enabled
            )

            # Verify command detection was logged
            mock_logger.info.assert_any_call(
                "Detected pytest command execution: pytest (tool: shell)"
            )

    def test_non_cline_agent_behavior(self, formatter, sample_pytest_output):
        """Test that non-Cline agents handle pytest compression correctly."""
        non_cline_session = Session(
            session_id="test-session",
            state=SessionState(pytest_compression_enabled=True),
            agent="openai",  # Non-Cline agent
        )

        tool_call_result = CommandResult(
            name="shell", message=sample_pytest_output, success=False
        )

        result = formatter.format_command_result_for_agent(
            tool_call_result, non_cline_session
        )

        # For non-Cline agents, should return regular chat completion format
        assert "tool_calls" not in result["choices"][0]["message"]
        assert "content" in result["choices"][0]["message"]

        # But compression should still be applied to the content
        content = result["choices"][0]["message"]["content"]
        assert len(content) < len(sample_pytest_output)
        assert "PASSED" not in content

    def test_edge_case_empty_output(self, formatter, session_with_compression_enabled):
        """Test handling of empty tool call output."""
        tool_call_result = CommandResult(name="shell", message="", success=True)

        result = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_enabled
        )

        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        message = args.get("result", "")

        # Should handle empty output gracefully
        assert message == ""

    def test_edge_case_single_line_output(
        self, formatter, session_with_compression_enabled
    ):
        """Test handling of single line tool call output."""
        tool_call_result = CommandResult(
            name="shell", message="test_example.py::test_success PASSED", success=True
        )

        result = formatter.format_command_result_for_agent(
            tool_call_result, session_with_compression_enabled
        )

        tool_call = result["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        message = args.get("result", "")

        # Single line should be preserved even if it contains PASSED
        assert message == "test_example.py::test_success PASSED"

    def test_enhanced_pytest_command_patterns(
        self, formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test that enhanced pytest command patterns are correctly detected and compressed."""
        enhanced_test_cases = [
            # Virtual environment patterns
            "./.venv/Scripts/python.exe -m pytest",
            "./.venv/bin/python -m pytest",
            ".\\.venv\\Scripts\\python.exe -m pytest",
            "./venv/Scripts/python.exe -m pytest",
            "./venv/bin/python -m pytest",
            # Relative path patterns
            "./python -m pytest",
            ".\\python.exe -m pytest",
            "./pytest",
            ".\\pytest.exe",
            # Complex commands with parameters
            "./.venv/Scripts/python.exe -m pytest tests/unit/ -v",
            "./.venv/bin/python -m pytest --tb=short",
            "./python -m pytest tests/ --cov=src",
        ]

        for command in enhanced_test_cases:
            # Create a mock message that contains the command and pytest output
            mock_message = f"$ {command}\n{sample_pytest_output}"

            tool_call_result = CommandResult(
                name="shell", message=mock_message, success=False
            )

            result = formatter.format_command_result_for_agent(
                tool_call_result, session_with_compression_enabled
            )

            tool_call = result["choices"][0]["message"]["tool_calls"][0]
            args = json.loads(tool_call["function"]["arguments"])
            compressed_message = args.get("result", "")

            # Verify compression was applied
            assert len(compressed_message) < len(
                mock_message
            ), f"Compression should be applied to: {command}"
            assert (
                "PASSED" not in compressed_message
            ), f"PASSED should be filtered out for: {command}"
            assert (
                "FAILED" in compressed_message
            ), f"FAILED should be preserved for: {command}"

    def test_false_positive_patterns(
        self, formatter, session_with_compression_enabled, sample_regular_output
    ):
        """Test that non-pytest commands are not falsely detected."""
        false_positive_cases = [
            "echo 'pytest'",
            "cat pytest.log",
            "grep pytest file.txt",
            "python my_script.py",
            "python --version",
            "echo 'This mentions pytest but is not a command'",
            "cat file_with_pytest_in_name.txt",
        ]

        for command in false_positive_cases:
            mock_message = f"$ {command}\n{sample_regular_output}"

            tool_call_result = CommandResult(
                name="shell", message=mock_message, success=True
            )

            result = formatter.format_command_result_for_agent(
                tool_call_result, session_with_compression_enabled
            )

            tool_call = result["choices"][0]["message"]["tool_calls"][0]
            args = json.loads(tool_call["function"]["arguments"])
            message = args.get("result", "")

            # Verify no compression was applied
            assert len(message) == len(
                mock_message
            ), f"No compression should be applied to: {command}"
            assert (
                message == mock_message
            ), f"Message should be unchanged for: {command}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
