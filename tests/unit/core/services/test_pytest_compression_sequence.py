"""
Tests for pytest compression sequence behavior.

Verifies that compression is only applied to command results and not to regular messages,
and that the compression behavior follows the expected sequence patterns.
"""

from unittest.mock import patch

import pytest
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
from src.core.services.response_manager_service import AgentResponseFormatter


class TestPytestCompressionSequence:
    """Test suite for pytest compression sequence behavior."""

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
    def sample_pytest_output(self):
        """Sample pytest output that should be compressed."""
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

    def test_compression_applied_only_to_command_results_not_regular_messages(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that compression is only applied to command results, not regular messages."""

        # Test 1: Regular message (no command result) - should NOT be compressed
        regular_message = (
            "This is a regular chat message about pytest but not a command result"
        )

        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            # For non-Cline agents, this would be processed as a regular message
            regular_result = type("RegularMessage", (), {"message": regular_message})()

            formatted_response = agent_formatter.format_command_result_for_agent(
                regular_result, session_with_compression_enabled
            )

            # For Cline agents, this should fall back to unknown_command tool call
            # because the object doesn't have the expected attributes
            assert "choices" in formatted_response
            assert "message" in formatted_response["choices"][0]

            # Check if it has tool_calls (fallback for Cline) or content (for non-Cline)
            if "tool_calls" in formatted_response["choices"][0]["message"]:
                # Cline agent fallback - check the unknown_command response
                tool_call = formatted_response["choices"][0]["message"]["tool_calls"][0]
                assert tool_call["function"]["name"] == "unknown_command"
                import json

                args = json.loads(tool_call["function"]["arguments"])
                assert "Unexpected result type" in args.get("result", "")
            else:
                # Non-Cline agent - should have regular content
                content = formatted_response["choices"][0]["message"]["content"]
                assert content == regular_message

            # Verify no compression logging occurred
            compression_calls = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
                and "compression" in str(call.args).lower()
            ]
            assert (
                len(compression_calls) == 0
            ), "Compression should not be applied to regular messages"

    def test_sequence_compression_behavior(
        self, agent_formatter, session_with_compression_enabled, sample_pytest_output
    ):
        """Test sequence: non-compressed -> compressed -> non-compressed."""

        with patch("src.core.services.response_manager_service.logger") as mock_logger:

            # Step 1: Non-pytest command result - should NOT be compressed
            non_pytest_command = CommandResult(
                name="npm-test",
                message="All npm tests passed successfully",
                success=True,
            )

            result1 = agent_formatter.format_command_result_for_agent(
                non_pytest_command, session_with_compression_enabled
            )

            # Verify it's a tool_calls response (Cline agent)
            assert "tool_calls" in result1["choices"][0]["message"]

            # Extract the result message
            tool_call = result1["choices"][0]["message"]["tool_calls"][0]
            import json

            args1 = json.loads(tool_call["function"]["arguments"])
            message1 = args1.get("result", "")

            # Message should be unchanged (no compression)
            assert message1 == "All npm tests passed successfully"

            # Verify no compression logging for non-pytest command
            compression_calls_step1 = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
            ]
            assert len(compression_calls_step1) == 0

            # Step 2: Pytest command result - SHOULD be compressed
            pytest_command = CommandResult(
                name="pytest", message=sample_pytest_output, success=False
            )

            result2 = agent_formatter.format_command_result_for_agent(
                pytest_command, session_with_compression_enabled
            )

            # Verify it's a tool_calls response
            assert "tool_calls" in result2["choices"][0]["message"]

            # Extract the result message
            tool_call2 = result2["choices"][0]["message"]["tool_calls"][0]
            args2 = json.loads(tool_call2["function"]["arguments"])
            message2 = args2.get("result", "")

            # Message should be compressed (shorter than original)
            assert len(message2) < len(sample_pytest_output)

            # Verify compression was applied
            assert "PASSED" not in message2, "PASSED lines should be filtered out"
            assert (
                "FAILED test_example.py::test_failure" in message2
            ), "Failure info should be preserved"
            assert (
                "========================= 1 failed, 2 passed in 0.12s ========================="
                in message2
            ), "Summary should be preserved"

            # Verify compression logging occurred
            compression_calls_step2 = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
                and "compression" in str(call.args).lower()
            ]
            assert (
                len(compression_calls_step2) > 0
            ), "Compression logging should occur for pytest commands"

            # Step 3: Another non-pytest command result - should NOT be compressed
            another_non_pytest_command = CommandResult(
                name="make-test",
                message="Build and test completed successfully",
                success=True,
            )

            result3 = agent_formatter.format_command_result_for_agent(
                another_non_pytest_command, session_with_compression_enabled
            )

            # Verify it's a tool_calls response
            assert "tool_calls" in result3["choices"][0]["message"]

            # Extract the result message
            tool_call3 = result3["choices"][0]["message"]["tool_calls"][0]
            args3 = json.loads(tool_call3["function"]["arguments"])
            message3 = args3.get("result", "")

            # Message should be unchanged (no compression)
            assert message3 == "Build and test completed successfully"

            # Verify no additional compression logging (only the one from step 2 should exist)
            all_compression_calls = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
                and "compression" in str(call.args).lower()
            ]

            # Verify compression occurred for pytest commands
            assert (
                len(all_compression_calls) > 0
            ), "Compression logging should occur for pytest commands"

    def test_compression_disabled_in_session(
        self, agent_formatter, sample_pytest_output
    ):
        """Test that compression is not applied when disabled in session."""

        # Create session with compression disabled
        state = SessionState(pytest_compression_enabled=False)
        session_disabled = Session(
            session_id="test-session", agent="cline", state=state
        )

        pytest_command = CommandResult(
            name="pytest", message=sample_pytest_output, success=False
        )

        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            result = agent_formatter.format_command_result_for_agent(
                pytest_command, session_disabled
            )

            # Extract the result message
            tool_call = result["choices"][0]["message"]["tool_calls"][0]
            import json

            args = json.loads(tool_call["function"]["arguments"])
            message = args.get("result", "")

            # Message should be unchanged (no compression applied)
            assert message == sample_pytest_output
            assert (
                "PASSED" in message
            ), "PASSED lines should be preserved when compression disabled"

            # Verify no compression logging occurred
            compression_calls = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
                and "compression" in str(call.args).lower()
            ]
            assert (
                len(compression_calls) == 0
            ), "Compression should not be applied when disabled"

    def test_non_command_result_objects_not_compressed(
        self, agent_formatter, session_with_compression_enabled
    ):
        """Test that non-command result objects are not compressed."""

        # Create an object that doesn't match command result patterns
        non_command_obj = type(
            "NonCommand",
            (),
            {
                "some_field": "This contains pytest output but is not a command result",
                "other_field": "test_example.py::test_success PASSED",
            },
        )()

        with patch("src.core.services.response_manager_service.logger") as mock_logger:
            result = agent_formatter.format_command_result_for_agent(
                non_command_obj, session_with_compression_enabled
            )

            # Should return as regular message content (not tool_calls for Cline agent fallback)
            assert "choices" in result
            assert "message" in result["choices"][0]

            # Verify no compression logging occurred
            compression_calls = [
                call
                for call in mock_logger.info.call_args_list
                if "pytest" in str(call.args).lower()
                and "compression" in str(call.args).lower()
            ]
            assert (
                len(compression_calls) == 0
            ), "Compression should not be applied to non-command objects"
