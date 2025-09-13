"""
Tests for pytest output compression feature.
"""

import pytest
from unittest.mock import Mock, patch

from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
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
        state = SessionState(pytest_compression_enabled=True)
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

    def test_filter_pytest_output_removes_target_lines(self, agent_formatter, sample_pytest_output):
        """Test that pytest output filtering removes the correct lines."""
        filtered = agent_formatter._filter_pytest_output(sample_pytest_output)
        
        # Lines that should be removed (timing info and passed tests)
        assert "test_example.py::test_success PASSED" not in filtered
        assert "test_example.py::test_failure PASSED" not in filtered  # PASSED timing info
        assert "test_example.py::test_another PASSED" not in filtered
        
        # Lines that should be kept (errors and failures)
        assert "FAILED test_example.py::test_failure" in filtered
        assert "FAILED test_example.py::test_failure - AssertionError: assert False" in filtered
        assert "def test_failure():" in filtered
        assert "assert False" in filtered
        assert "AssertionError: assert False" in filtered
        
        # Check that the structure is maintained
        lines = filtered.split('\n')
        assert len(lines) > 0
        assert any("test session starts" in line for line in lines)

    def test_apply_pytest_compression_with_pytest_command_enabled(self, agent_formatter, session_with_compression_enabled):
        """Test pytest compression is applied for pytest commands when enabled."""
        command_name = "pytest"
        message = "Line 1\nFAILED something\nLine 3\ns setup\nLine 5"
        
        result = agent_formatter._apply_pytest_compression(command_name, message, session_with_compression_enabled)
        
        # Should apply compression - keep FAILED, filter timing info
        assert "FAILED something" in result
        assert "s setup" not in result
        assert "Line 1" in result
        assert "Line 3" in result
        assert "Line 5" in result

    def test_apply_pytest_compression_with_pytest_command_disabled(self, agent_formatter, session_with_compression_disabled):
        """Test pytest compression is not applied when disabled."""
        command_name = "pytest"
        message = "Line 1\nFAILED something\nLine 3\ns setup\nLine 5"
        
        result = agent_formatter._apply_pytest_compression(command_name, message, session_with_compression_disabled)
        
        # Should not apply compression
        assert result == message

    def test_apply_pytest_compression_with_non_pytest_command(self, agent_formatter, session_with_compression_enabled):
        """Test pytest compression is not applied for non-pytest commands."""
        command_name = "npm test"
        message = "Line 1\nFAILED something\nLine 3\ns setup 0.1s\nLine 5"
        
        result = agent_formatter._apply_pytest_compression(command_name, message, session_with_compression_enabled)
        
        # Should not apply compression
        assert result == message

    def test_apply_pytest_compression_with_empty_message(self, agent_formatter, session_with_compression_enabled):
        """Test pytest compression handles empty messages gracefully."""
        result = agent_formatter._apply_pytest_compression("pytest", "", session_with_compression_enabled)
        assert result == ""

    def test_apply_pytest_compression_with_none_message(self, agent_formatter, session_with_compression_enabled):
        """Test pytest compression handles None messages gracefully."""
        result = agent_formatter._apply_pytest_compression("pytest", None, session_with_compression_enabled)
        assert result is None

    def test_format_command_result_for_cline_applies_compression(self, agent_formatter, session_with_compression_enabled):
        """Test that command result formatting for Cline applies compression."""
        command_result = CommandResult(
            name="pytest",
            success=True,
            message="Line 1\nFAILED test\nLine 3\ns call\nLine 5"
        )
        
        with patch.object(agent_formatter, '_create_tool_calls_response') as mock_create_response:
            mock_create_response.return_value = {"mock": "response"}
            
            result = agent_formatter.format_command_result_for_agent(command_result, session_with_compression_enabled)
            
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

    def test_format_command_result_for_non_cline_applies_compression(self, agent_formatter, session_with_compression_enabled):
        """Test that command result formatting for non-Cline applies compression."""
        command_result = CommandResult(
            name="pytest",
            success=True,
            message="Line 1\nFAILED test\nLine 3\ns teardown\nLine 5"
        )
        
        # Create a non-Cline session
        session = Session(session_id="test-session", agent="other", state=session_with_compression_enabled.state)
        
        result = agent_formatter.format_command_result_for_agent(command_result, session)
        
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
            "FAILED test_case",    # Should be kept (errors)
            "failed test_case",    # Should be kept (errors)
            "Test FAILED",         # Should be kept (errors)
            "0.1s setup",         # Should be filtered (matches pattern)
            "setup took 1.5s",    # Should be kept (regular text)
            "s call",             # Should be filtered (timing)
            "call function",      # Should be kept (regular text)
            "s teardown",         # Should be filtered (timing)
            "teardown method",    # Should be kept (regular text)
            "PASSED test_case",   # Should be filtered (success)
            "Regular line",       # Should be kept (regular text)
        ]
        
        filtered = agent_formatter._filter_pytest_output('\n'.join(test_lines))
        filtered_lines = filtered.split('\n')
        
        # Should keep FAILED lines and filter out timing/PASSED lines
        expected_remaining = [
            "FAILED test_case",
            "failed test_case", 
            "Test FAILED",
            "setup took 1.5s",
            "call function",
            "teardown method",
            "Regular line"
        ]
        
        assert len(filtered_lines) == len(expected_remaining)
        for expected_line in expected_remaining:
            assert expected_line in filtered_lines

    def test_compression_statistics_logging(self, agent_formatter):
        """Test that compression statistics are logged correctly."""
        with patch('src.core.services.response_manager_service.logger') as mock_logger:
            agent_formatter._filter_pytest_output("Line 1\nFAILED\nLine 3")
            
            # Should log compression statistics
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]
            assert "Pytest compression applied" in log_message
            assert "reduction" in log_message