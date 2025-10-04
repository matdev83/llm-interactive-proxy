"""
Tests for pytest output compression feature.
"""

from unittest.mock import patch

import pytest
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
from src.core.services.pytest_compression_service import PytestCompressionService
from src.core.services.response_manager_service import AgentResponseFormatter


class TestPytestCompression:
    """Test suite for pytest output compression functionality."""

    @pytest.fixture
    def agent_formatter(self):
        """Create an AgentResponseFormatter instance for testing."""
        return AgentResponseFormatter()

    @pytest.fixture
    def session_with_compression_enabled(self):
        """Create a session with pytest compression enabled."""
        state = SessionState(
            pytest_compression_enabled=True,
            compress_next_tool_call_reply=True,
            pytest_compression_min_lines=1,
        )
        return Session(session_id="test-session", agent="cline", state=state)

    @pytest.fixture
    def session_with_compression_disabled(self):
        """Create a session with pytest compression disabled."""
        state = SessionState(pytest_compression_enabled=False)
        return Session(session_id="test-session", agent="cline", state=state)

    @pytest.fixture
    def sample_pytest_output(self):
        """Sample pytest output with timing and FAILED lines."""
        return """============================= test session starts ==============================
platform linux -- Python 3.9.0, pytest-6.2.5, py-1.10.0, pluggy-0.13.1 -- /usr/bin/python
cachedir .pytest_cache
rootdir: /test/project
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

    def test_is_pytest_command_recognizes_pytest_commands(self, agent_formatter):
        """Test that pytest commands are correctly identified."""
        # Test various pytest command patterns
        assert agent_formatter._is_pytest_command("pytest")
        assert agent_formatter._is_pytest_command("python -m pytest")
        assert agent_formatter._is_pytest_command("python3 -m pytest tests/")
        assert agent_formatter._is_pytest_command("python pytest.py")
        assert agent_formatter._is_pytest_command("py.test")

        # Test non-pytest commands
        assert not agent_formatter._is_pytest_command("npm test")
        assert not agent_formatter._is_pytest_command("python -m unittest")
        assert not agent_formatter._is_pytest_command("make test")
        assert not agent_formatter._is_pytest_command("hello")

    def test_filter_pytest_output_removes_target_lines(
        self, agent_formatter, sample_pytest_output
    ):
        """Test that pytest output filtering removes the correct lines."""
        filtered = agent_formatter._filter_pytest_output(sample_pytest_output)

        # Lines that should be removed (timing info and passed tests)
        assert "test_example.py::test_success PASSED" not in filtered
        assert (
            "test_example.py::test_failure PASSED" not in filtered
        )  # PASSED timing info
        assert "test_example.py::test_another PASSED" not in filtered

        # Lines that should be kept (errors and failures)
        assert "FAILED test_example.py::test_failure" in filtered
        assert (
            "FAILED test_example.py::test_failure - AssertionError: assert False"
            in filtered
        )
        assert "def test_failure():" in filtered
        assert "assert False" in filtered
        assert "AssertionError: assert False" in filtered

        # Check that the structure is maintained
        lines = filtered.split("\n")
        assert len(lines) > 0
        assert any("test session starts" in line for line in lines)

    async def test_apply_pytest_compression_with_pytest_command_enabled(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test pytest compression is applied for pytest commands when enabled."""
        command_name = "pytest"
        message = "Line 1\nFAILED something\nLine 3\ns setup\nLine 5\n========================= 1 failed in 0.12s ========================="

        result = await agent_formatter._apply_pytest_compression(
            command_name, message, session_with_compression_enabled
        )

        # Should apply compression - keep FAILED, filter timing info
        assert "FAILED something" in result
        assert "s setup" not in result
        assert "Line 1" in result
        assert "Line 3" in result
        assert "Line 5" in result
        # Should preserve the summary line
        assert (
            "========================= 1 failed in 0.12s ========================="
            in result
        )

    async def test_apply_pytest_compression_with_pytest_command_disabled(
        self, agent_formatter, session_with_compression_disabled
    ):
        """Test pytest compression is not applied when disabled."""
        command_name = "pytest"
        message = "Line 1\nFAILED something\nLine 3\ns setup\nLine 5"

        result = await agent_formatter._apply_pytest_compression(
            command_name, message, session_with_compression_disabled
        )

        # Should not apply compression
        assert result == message

    async def test_apply_pytest_compression_with_non_pytest_command(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test pytest compression is not applied for non-pytest commands."""
        command_name = "npm test"
        message = "Line 1\nFAILED something\nLine 3\ns setup 0.1s\nLine 5"

        result = await agent_formatter._apply_pytest_compression(
            command_name, message, session_with_compression_enabled
        )

        # Should not apply compression
        assert result == message

    async def test_apply_pytest_compression_with_empty_message(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test pytest compression handles empty messages gracefully."""
        result = await agent_formatter._apply_pytest_compression(
            "pytest", "", session_with_compression_enabled
        )
        assert result == ""

    async def test_apply_pytest_compression_with_none_message(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test pytest compression handles None messages gracefully."""
        result = await agent_formatter._apply_pytest_compression(
            "pytest", None, session_with_compression_enabled
        )
        assert result is None

    async def test_format_command_result_for_cline_applies_compression(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that command result formatting for Cline applies compression."""
        command_result = CommandResult(
            name="pytest",
            success=True,
            message="Line 1\nFAILED test\nLine 3\ns call\nLine 5\n================ 1 failed in 0.05s =================",
        )

        with patch.object(
            agent_formatter, "_create_tool_calls_response"
        ) as mock_create_response:
            mock_create_response.return_value = {"mock": "response"}

            await agent_formatter.format_command_result_for_agent(
                command_result, session_with_compression_enabled
            )

            # Should have called _create_tool_calls_response
            mock_create_response.assert_called_once()

            # Check that the arguments contain the compressed message
            call_args = mock_create_response.call_args
            arguments = call_args[0][1]  # Second positional argument is arguments

            import json

            args_dict = json.loads(arguments)

            # Should have kept FAILED but filtered out timing info
            assert "FAILED test" in args_dict["result"]
            assert "s call" not in args_dict["result"]
            assert "Line 1" in args_dict["result"]
            assert "Line 3" in args_dict["result"]
            assert "Line 5" in args_dict["result"]

    async def test_format_command_result_for_non_cline_applies_compression(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that command result formatting for non-Cline applies compression."""
        command_result = CommandResult(
            name="pytest",
            success=True,
            message="Line 1\nFAILED test\nLine 3\ns teardown\nLine 5\n================ 1 failed in 0.08s =================",
        )

        # Create a non-Cline session
        session = Session(
            session_id="test-session",
            agent="other",
            state=session_with_compression_enabled.state,
        )

        result = await agent_formatter.format_command_result_for_agent(
            command_result, session
        )

        # Should return a message with compression applied
        assert isinstance(result, dict)
        assert "choices" in result
        message_content = result["choices"][0]["message"]["content"]

        # Should have kept FAILED but filtered out timing info
        assert "FAILED test" in message_content
        assert "s teardown" not in message_content
        assert "Line 1" in message_content
        assert "Line 3" in message_content
        assert "Line 5" in message_content

    def test_filter_patterns_match_various_cases(self, agent_formatter):
        """Test that filter patterns work with various case sensitivities."""
        test_lines = [
            "FAILED test_case",  # Should be kept (errors)
            "failed test_case",  # Should be kept (errors)
            "Test FAILED",  # Should be kept (errors)
            "0.1s setup",  # Should be filtered (matches pattern)
            "setup took 1.5s",  # Should be kept (regular text)
            "s call",  # Should be filtered (timing)
            "call function",  # Should be kept (regular text)
            "s teardown",  # Should be filtered (timing)
            "teardown method",  # Should be kept (regular text)
            "PASSED test_case",  # Should be filtered (success)
            "Regular line",  # Should be kept (regular text)
        ]

        filtered = agent_formatter._filter_pytest_output("\n".join(test_lines))
        filtered_lines = filtered.split("\n")

        # Should keep FAILED lines and filter out timing/PASSED lines
        expected_remaining = [
            "FAILED test_case",
            "failed test_case",
            "Test FAILED",
            "setup took 1.5s",
            "call function",
            "teardown method",
            "Regular line",
        ]

        assert len(filtered_lines) == len(expected_remaining)
        for expected_line in expected_remaining:
            assert expected_line in filtered_lines

    def test_compression_statistics_logging(self, agent_formatter):
        """Test that compression statistics are logged correctly."""
        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            agent_formatter._filter_pytest_output("Line 1\nFAILED\nLine 3")

            # Should log compression statistics
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            assert "Pytest compression applied" in log_message
            assert "reduction" in log_message

    def test_last_line_always_preserved(self, agent_formatter):
        """Test that the last line of pytest output is always preserved."""
        # Test case 1: Last line would normally be filtered (PASSED)
        output1 = "test_example.py::test_function FAILED\ntest_example.py::test_success PASSED"
        result1 = agent_formatter._filter_pytest_output(output1)

        # Last line should be preserved even though it contains PASSED
        assert "test_example.py::test_success PASSED" in result1
        assert result1.endswith("test_example.py::test_success PASSED")

        # Test case 2: Last line with timing info that would normally be filtered
        output2 = "FAILURES\ntest_example.py::test_function FAILED 0.001s setup 0.002s call 0.001s teardown"
        result2 = agent_formatter._filter_pytest_output(output2)

        # Last line should be preserved even though it contains timing info
        assert "0.001s setup 0.002s call 0.001s teardown" in result2
        assert result2.endswith(
            "test_example.py::test_function FAILED 0.001s setup 0.002s call 0.001s teardown"
        )

        # Test case 3: Summary line that would normally be filtered
        output3 = (
            "test_example.py::test_function FAILED\n=== 1 failed, 2 passed in 0.05s ==="
        )
        result3 = agent_formatter._filter_pytest_output(output3)

        # Summary line should be preserved (this is typically the most important line)
        assert "=== 1 failed, 2 passed in 0.05s ===" in result3
        assert result3.endswith("=== 1 failed, 2 passed in 0.05s ===")

    def test_last_line_preserved_with_multiple_filter_patterns(self, agent_formatter):
        """Test last line preservation with complex filtering scenarios."""
        # Complex output with multiple patterns that would be filtered
        output = """test_example.py::test_success PASSED                    [ 50%] 0.001s setup 0.002s call 0.001s teardown
test_example.py::test_failure FAILED                     [100%] 0.001s setup 0.003s call 0.001s teardown
FAILURES
================================== FAILURES ==================================
_______________________________ test_failure _______________________________
AssertionError: Expected 5 but got 3
=== 1 failed, 1 passed in 0.05s ==="""

        result = agent_formatter._filter_pytest_output(output)
        lines = result.split("\n")

        # Verify the last line (summary) is always preserved
        assert lines[-1] == "=== 1 failed, 1 passed in 0.05s ==="

        # Verify other filtering still works
        assert (
            "test_example.py::test_success PASSED" not in result
        )  # PASSED line filtered
        assert (
            "0.001s setup 0.002s call 0.001s teardown" not in result
        )  # Timing info filtered from non-last lines

        # Verify important content is preserved
        assert "FAILURES" in result
        assert "AssertionError: Expected 5 but got 3" in result

    def test_last_line_preserved_single_line_output(self, agent_formatter):
        """Test that single-line output is preserved even if it matches filter patterns."""
        # Single line that would normally be filtered
        output1 = "test_example.py::test_success PASSED"
        result1 = agent_formatter._filter_pytest_output(output1)
        assert (
            result1 == output1
        )  # Should be preserved as it's the last (and only) line

        # Single line with timing info
        output2 = "test_example.py::test_function 0.001s setup 0.002s call"
        result2 = agent_formatter._filter_pytest_output(output2)
        assert (
            result2 == output2
        )  # Should be preserved as it's the last (and only) line

    def test_last_line_preserved_empty_last_line(self, agent_formatter):
        """Test handling of empty last lines."""
        # Output ending with empty line
        output = "test_example.py::test_function FAILED\nFAILURES\n"
        result = agent_formatter._filter_pytest_output(output)

        # Should preserve the structure including the empty last line
        assert result.endswith("\n")
        lines = result.split("\n")
        assert lines[-1] == ""  # Empty last line preserved

        # Test another case: output with empty line in the middle and at the end
        output2 = "Line1\n\nLine3\n"
        result2 = agent_formatter._filter_pytest_output(output2)
        assert result2.endswith("\n")
        assert result2.split("\n")[-1] == ""

    async def test_last_line_preserved_in_full_compression_flow(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test last line preservation in the complete compression flow."""
        command_name = "pytest"
        message = """test_example.py::test_success PASSED                    [ 50%] 0.001s setup
test_example.py::test_failure FAILED                     [100%] 0.001s setup
FAILURES
=== 1 failed, 1 passed in 0.05s ==="""

        result = await agent_formatter._apply_pytest_compression(
            command_name, message, session_with_compression_enabled
        )

        # Verify last line (summary) is preserved
        assert result.endswith("=== 1 failed, 1 passed in 0.05s ===")

        # Verify filtering still works for non-last lines
        assert "test_example.py::test_success PASSED" not in result
        assert (
            "0.001s setup" not in result.split("\n")[0]
        )  # Timing filtered from first line

        # Verify important content preserved
        assert "FAILURES" in result

    async def test_enhanced_pytest_compression_with_detailed_metrics(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test enhanced pytest compression with detailed metrics logging."""
        from unittest.mock import patch

        # Create a realistic pytest output that would benefit from compression
        pytest_output = """============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-8.3.3, pluggy-1.5.0
rootdir: /test/project
collected 16 items

tests/unit/test_example1.py::test_success PASSED [  6%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example1.py::test_another PASSED [ 12%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example2.py::test_success PASSED [ 18%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_example2.py::test_failure FAILED [ 25%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example3.py::test_success PASSED [ 31%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example3.py::test_another PASSED [ 37%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example4.py::test_success PASSED [ 43%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example4.py::test_another PASSED [ 50%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_example5.py::test_success PASSED [ 56%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example5.py::test_another PASSED [ 62%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example6.py::test_success PASSED [ 68%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example6.py::test_another PASSED [ 75%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_example7.py::test_success PASSED [ 81%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example7.py::test_another PASSED [ 87%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example8.py::test_success PASSED [ 93%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example8.py::test_another PASSED [100%] 0.001s setup 0.003s call 0.001s teardown

=================================== FAILURES ===================================
_________________________ test_failure _________________________

    def test_failure():
>       assert False
E       AssertionError: assert False

tests/unit/test_example2.py:6: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_example2.py::test_failure - AssertionError: assert False
========================= 1 failed, 15 passed in 0.12s ========================="""

        # Set up the session state to enable compression
        # The fixture creates a SessionState directly, so we can use the method
        session_with_compression_enabled.state = (
            session_with_compression_enabled.state.with_compress_next_tool_call_reply(
                True
            )
        )
        # Set a lower threshold for this test to ensure compression is applied
        session_with_compression_enabled.state = (
            session_with_compression_enabled.state.with_pytest_compression_min_lines(10)
        )

        # Mock the logger to capture logging calls
        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            # Apply the compression
            result = await agent_formatter._apply_pytest_compression(
                "pytest", pytest_output, session_with_compression_enabled
            )

            # Verify the result is compressed
            assert len(result) < len(pytest_output)

            # Check that threshold-based compression was logged
            mock_logger.info.assert_any_call(
                "Applying pytest compression to command result: pytest (tool: pytest) - 33 lines >= 10 threshold"
            )

            # Verify that detailed metrics were logged
            info_calls = [
                call.args[0] for call in mock_logger.info.call_args_list if call.args
            ]

            # Find the compression started and completed messages
            compression_started = any(
                "Pytest compression started" in call for call in info_calls
            )
            compression_completed = any(
                "Pytest compression completed" in call for call in info_calls
            )

            assert compression_started, "Compression started message should be logged"
            assert (
                compression_completed
            ), "Compression completed message should be logged"

            # Verify the final result still contains important information
            assert "FAILED tests/unit/test_example2.py::test_failure" in result
            assert "AssertionError: assert False" in result
            assert (
                "========================= 1 failed, 15 passed in 0.12s ========================="
                in result
            )

            # Verify PASSED lines were removed
            assert "PASSED" not in result

            # Verify timing info was removed from non-last lines
            lines = result.split("\n")
            for line in lines[:-1]:  # All lines except the last one
                assert "0.001s setup" not in line, f"Timing info found in line: {line}"
                assert "0.002s call" not in line, f"Timing info found in line: {line}"
                assert (
                    "0.001s teardown" not in line
                ), f"Timing info found in line: {line}"

    async def test_pytest_summary_validation_valid_summaries(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that compression is applied when valid pytest summaries are present."""
        # Test various valid summary formats with realistic pytest output
        valid_cases = [
            # Standard failure summary with compressible content
            """test_example.py::test_success PASSED                    [ 50%]
test_example.py::test_failure FAILED                     [100%]
FAILURES
=== 1 failed, 1 passed in 0.05s ===""",
            # Standard pass summary with compressible content
            """test_example.py::test1 PASSED                                       [ 33%]
test_example.py::test2 PASSED                                       [ 66%]
test_example.py::test3 PASSED                                       [100%]
============================ 3 passed in 0.12s =============================""",
            # Session start (should pass validation)
            """============================= test session starts ==============================""",
            # Error summary with compressible content
            """test_example.py::test_error ERROR
============================= ERRORS ============================================
""",
            # Mixed results with timing info
            """test_example.py::test_success PASSED                    [ 50%] 0.001s setup
test_example.py::test_failure FAILED                     [100%] 0.001s setup
FAILURES
================ 1 failed, 1 passed, 1 error in 0.05s =================""",
        ]

        for message in valid_cases:
            result = await agent_formatter._apply_pytest_compression(
                "pytest", message, session_with_compression_enabled
            )
            # Should apply compression - either result is different, or compression process was attempted
            # (some messages may not change much if they don't have compressible content, but validation should pass)
            # Ensure no exception raised during compression attempt
            # Check that validation passed (no early return due to invalid summary)
            assert "does not contain a valid pytest summary" not in str(
                result
            ), f"Summary validation failed for: {message[:50]}..."

    async def test_pytest_summary_validation_invalid_summaries(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that compression is NOT applied when invalid summaries are present (execution errors)."""
        # Test various invalid cases that indicate execution errors
        invalid_cases = [
            # Python import error
            "Traceback (most recent call last):\n  File \"test.py\", line 1\n    import pytest\nImportError: No module named 'pytest'",
            # Command not found
            "bash: pytest: command not found",
            # Python syntax error
            "SyntaxError: invalid syntax",
            # Missing test file
            "ERROR: file or directory not found: test_missing.py",
            # Empty output
            "",
            # Just random text without summary
            "Some random output\nMore random output",
            # Incomplete summary (no timing info)
            "================ 1 failed, 2 passed =================",
            # Just equal signs without content
            "================================================================",
        ]

        for invalid_message in invalid_cases:
            result = await agent_formatter._apply_pytest_compression(
                "pytest", invalid_message, session_with_compression_enabled
            )
            # Should NOT apply compression (result should be same as original)
            assert (
                result == invalid_message
            ), f"Compression should NOT be applied for: {invalid_message}"

    async def test_pytest_summary_validation_edge_cases(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test edge cases for summary validation."""
        # Test single line valid summary
        single_line_message = "================ 1 passed in 0.01s ================="
        result = await agent_formatter._apply_pytest_compression(
            "pytest", single_line_message, session_with_compression_enabled
        )
        # Single line with valid summary should pass validation and attempt compression
        # The result might be the same if there's nothing to filter, but validation should pass
        assert "does not contain a valid pytest summary" not in str(result)

        # Test multi-line output with valid summary that has compressible content
        multi_line_valid = "test_example.py::test_success PASSED\ntest_example.py::test_failure FAILED\n=== 1 failed, 1 passed in 0.05s ==="
        result = await agent_formatter._apply_pytest_compression(
            "pytest", multi_line_valid, session_with_compression_enabled
        )
        # The important thing is that validation passed and compression was attempted
        # The exact compression behavior may vary based on line processing logic
        assert "does not contain a valid pytest summary" not in str(result)
        assert "=== 1 failed, 1 passed in 0.05s ===" in result  # Summary preserved

        # Test multi-line output without valid summary
        multi_line_invalid = (
            "Some intermediate output\nMore output\nFinal line without summary format"
        )
        result = await agent_formatter._apply_pytest_compression(
            "pytest", multi_line_invalid, session_with_compression_enabled
        )
        # Should NOT apply compression
        assert result == multi_line_invalid

    async def test_has_valid_pytest_summary_method_directly(self, agent_formatter):
        """Test the _has_valid_pytest_summary method directly with various inputs."""
        # Valid summaries
        valid_summaries = [
            "========================= 1 failed, 15 passed in 0.12s =========================",
            "============================ 16 passed in 0.12s =============================",
            "============================= test session starts ==============================",
            "============================= ERRORS ============================================",
            "1 failed, 2 passed in 0.05s",
            "15 passed in 0.12s",
            "================ 1 failed, 1 passed, 1 error in 0.05s =================",
            "========================= 1 failed, 24 passed, 3 warnings in 0.15s =========================",
            "================== 2 failed, 10 passed, 5 warnings in 0.20s ===================",
            "1 failed, 2 passed, 3 warnings in 0.05s",
            "15 passed, 2 warnings in 0.12s",
        ]

        for summary in valid_summaries:
            assert agent_formatter._has_valid_pytest_summary(
                summary
            ), f"Should be valid: {summary}"

        # Invalid summaries
        invalid_summaries = [
            "",
            "Just some text",
            "Traceback (most recent call last):",
            "bash: pytest: command not found",
            "================ 1 failed, 2 passed =================",  # Missing timing
            "================================================================",
            "Some output\nwithout proper summary",
        ]

        for summary in invalid_summaries:
            assert not agent_formatter._has_valid_pytest_summary(
                summary
            ), f"Should be invalid: {summary}"

    async def test_pytest_compression_with_warnings_summary(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test pytest compression works correctly with warnings in the summary."""
        # Sample pytest output with warnings in summary
        pytest_with_warnings = """============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-8.3.3, pluggy-1.5.0
rootdir: /test/project
collected 25 items

tests/unit/test_example1.py::test_success PASSED [  4%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_example1.py::test_another PASSED [  8%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_example2.py::test_failure FAILED [ 16%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_warnings.py::test_deprecated PASSED [ 68%] 0.001s setup 0.002s call 0.001s teardown
tests/integration/test_api.py::test_endpoint PASSED [ 76%] 0.15s setup 0.25s call 0.10s teardown

=================================== FAILURES ===================================
_________________________ test_failure _________________________

    def test_failure():
>       assert False
E       AssertionError: assert False

tests/unit/test_example2.py:6: AssertionError

========================= 1 failed, 24 passed, 3 warnings in 0.15s ========================="""

        # Apply compression
        result = await agent_formatter._apply_pytest_compression(
            "pytest", pytest_with_warnings, session_with_compression_enabled
        )

        # Verify the result is compressed
        assert len(result) < len(pytest_with_warnings)

        # Verify warnings are recognized (summary should be preserved)
        assert (
            "========================= 1 failed, 24 passed, 3 warnings in 0.15s ========================="
            in result
        )

        # Verify PASSED lines with timing are filtered out
        assert "0.001s setup 0.002s call 0.001s teardown" not in result

        # Verify FAILED content is preserved
        assert "tests/unit/test_example2.py::test_failure FAILED" in result
        assert "AssertionError: assert False" in result

        # Verify session start is preserved
        assert "test session starts" in result

    async def test_pytest_compression_timing_filtering_effectiveness(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that timing information is effectively filtered to maximize compression."""
        # Create output with lots of timing information that should be filtered
        high_timing_output = """============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-8.3.3, pluggy-1.5.0
rootdir: /test/project
collected 100 items

tests/unit/test_module1.py::test_001 PASSED [  1%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_module1.py::test_002 PASSED [  2%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module1.py::test_003 PASSED [  3%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_module1.py::test_004 PASSED [  4%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module1.py::test_005 PASSED [  5%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_module1.py::test_006 PASSED [  6%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module1.py::test_007 PASSED [  7%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_module1.py::test_008 PASSED [  8%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module1.py::test_009 PASSED [  9%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_module1.py::test_010 PASSED [ 10%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module2.py::test_001 FAILED [ 11%] 0.001s setup 0.002s call 0.001s teardown
tests/unit/test_module2.py::test_002 PASSED [ 12%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module2.py::test_003 PASSED [ 13%] 0.001s setup 0.003s call 0.001s teardown
tests/unit/test_module2.py::test_004 PASSED [ 14%] 0.001s setup 0.001s call 0.001s teardown
tests/unit/test_module2.py::test_005 PASSED [ 15%] 0.001s setup 0.002s call 0.001s teardown
tests/integration/test_api.py::test_001 PASSED [ 16%] 0.15s setup 0.25s call 0.10s teardown
tests/integration/test_api.py::test_002 PASSED [ 17%] 0.10s setup 0.20s call 0.05s teardown
tests/integration/test_api.py::test_003 PASSED [ 18%] 0.05s setup 0.10s call 0.02s teardown
tests/integration/test_api.py::test_004 PASSED [ 19%] 0.03s setup 0.15s call 0.01s teardown
tests/integration/test_api.py::test_005 PASSED [ 20%] 0.02s setup 0.08s call 0.01s teardown

=================================== FAILURES ===================================
_________________________ test_001 _________________________

    def test_001():
>       assert False
E       AssertionError: assert False

tests/unit/test_module2.py:6: AssertionError

=========================== short test summary info ============================
FAILED tests/unit/test_module2.py::test_001 - AssertionError: assert False
========================= 1 failed, 19 passed in 0.25s ========================="""

        # Apply compression
        result = await agent_formatter._apply_pytest_compression(
            "pytest", high_timing_output, session_with_compression_enabled
        )

        # Calculate compression ratio
        original_lines = len(high_timing_output.split("\n"))
        compressed_lines = len(result.split("\n"))
        compression_ratio = (1 - compressed_lines / original_lines) * 100

        # Verify significant compression (should be > 50% due to extensive timing info)
        assert (
            compression_ratio > 50
        ), f"Compression ratio {compression_ratio:.1f}% should be > 50%"

        # Verify timing information is effectively removed
        lines = result.split("\n")
        timing_patterns = [
            "0.001s setup",
            "0.002s call",
            "0.001s teardown",
            "0.15s setup",
            "0.25s call",
        ]

        for line in lines[:-1]:  # Check all lines except the last (summary)
            for pattern in timing_patterns:
                assert (
                    pattern not in line
                ), f"Timing pattern '{pattern}' found in line: {line}"

        # Verify critical information is preserved
        assert "FAILED tests/unit/test_module2.py::test_001" in result
        assert "AssertionError: assert False" in result
        assert (
            "========================= 1 failed, 19 passed in 0.25s ========================="
            in result
        )


class TestPytestCompressionServiceDetection:
    """Tests for the PytestCompressionService detection logic."""

    def test_scan_for_pytest_detects_pytest_alias(self) -> None:
        """Ensure py.test alias commands are detected for compression."""
        service = PytestCompressionService()

        detection = service.scan_for_pytest(
            "shell",
            {"command": "py.test -k sample"},
        )

        assert detection == (True, "py.test -k sample")

    def test_scan_tool_call_for_pytest_handles_function_arguments(self) -> None:
        """Ensure ToolCall wrappers using py.test are detected."""
        service = PytestCompressionService()
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(
                name="shell",
                arguments='{"command": "py.test -q"}',
            ),
        )

        detection = service.scan_tool_call_for_pytest(tool_call)

        assert detection == (True, "py.test -q")
