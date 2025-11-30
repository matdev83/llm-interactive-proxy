"""Unit tests for CompletionSignalDetector.

This test suite validates the CompletionSignalDetector's ability to identify
completion signals through:
1. Explicit completion tool names (e.g., attempt_completion from Cline/Roo-Code)
2. Streaming finish_reason markers (e.g., "stop", "tool_calls", "length")

The detector no longer uses pattern matching against response text, as that
approach was unreliable and prone to false positives.
"""

from __future__ import annotations

from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)


class TestCompletionSignalDetector:
    """Test suite for CompletionSignalDetector class."""

    def test_completion_tool_detection(self) -> None:
        """Test detection of completion tool names."""
        # Positive cases - should be detected
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="mark_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="finish_task")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="complete") is True
        )
        assert CompletionSignalDetector.is_completion_signal(tool_name="done") is True

        # Case variations should work
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="TASK_COMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="Task_Complete")
            is True
        )
        assert CompletionSignalDetector.is_completion_signal(tool_name="DONE") is True

    def test_non_completion_tool_rejection(self) -> None:
        """Test that non-completion tools are not detected."""
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="write_file")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="read_file")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="execute_command")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="run_tests")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="pytest") is False
        )

    def test_attempt_completion_tool_detection(self) -> None:
        """Test detection of attempt_completion tool (used by Cline/Roo-Code)."""
        # This is the most common completion tool used by real agents
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="attempt_completion"
            )
            is True
        )

        # Case variations should work
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="ATTEMPT_COMPLETION"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="Attempt_Completion"
            )
            is True
        )

        # With hyphens instead of underscores
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="attempt-completion"
            )
            is True
        )

    def test_finish_tool_detection(self) -> None:
        """Test detection of finish tool (used by OpenHands/OpenDevin)."""
        # This is the completion tool used by OpenHands (formerly OpenDevin)
        assert CompletionSignalDetector.is_completion_signal(tool_name="finish") is True

        # Case variations should work
        assert CompletionSignalDetector.is_completion_signal(tool_name="FINISH") is True
        assert CompletionSignalDetector.is_completion_signal(tool_name="Finish") is True

    def test_finish_reason_detection(self) -> None:
        """Test detection of finish_reason markers from streaming responses."""
        # Standard finish reasons from OpenAI/Anthropic APIs
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="stop") is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="tool_calls")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="length")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="end_turn")
            is True
        )

        # Case insensitive
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="STOP") is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="Stop") is True
        )

        # With whitespace
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason=" stop ")
            is True
        )

    def test_finish_reason_in_metadata(self) -> None:
        """Test detection of finish_reason in metadata dict."""
        # finish_reason in metadata
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata={"finish_reason": "stop"}
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata={"finish_reason": "tool_calls"}
            )
            is True
        )

        # Other metadata should not affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata={"other_key": "value"}
            )
            is False
        )

        # Empty metadata
        assert CompletionSignalDetector.is_completion_signal(metadata={}) is False

    def test_combined_tool_and_finish_reason_detection(self) -> None:
        """Test detection when both tool name and finish_reason are present."""
        # Both indicate completion
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="attempt_completion", finish_reason="stop"
            )
            is True
        )

        # Tool name indicates completion, finish_reason does not
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="attempt_completion", finish_reason="unknown"
            )
            is True
        )

        # finish_reason indicates completion, tool name does not
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="write_file", finish_reason="stop"
            )
            is True
        )

        # Neither indicates completion
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="write_file", finish_reason="unknown"
            )
            is False
        )

    def test_empty_and_none_handling(self) -> None:
        """Test handling of empty strings and None values."""
        # Empty tool name
        assert CompletionSignalDetector.is_completion_signal(tool_name="") is False

        # None tool name
        assert CompletionSignalDetector.is_completion_signal(tool_name=None) is False

        # Empty finish_reason
        assert CompletionSignalDetector.is_completion_signal(finish_reason="") is False

        # None finish_reason
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason=None) is False
        )

        # All None/empty
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name=None, finish_reason=None, metadata=None
            )
            is False
        )

    def test_case_insensitive_tool_matching(self) -> None:
        """Test that tool name matching is case-insensitive."""
        # Tool names
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="TASK_COMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="Task_Complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task_COMPLETE")
            is True
        )
        assert CompletionSignalDetector.is_completion_signal(tool_name="DONE") is True

    def test_normalization_with_underscores_and_hyphens(self) -> None:
        """Test that underscores and hyphens are normalized in tool names."""
        # These should all be detected as the same tool
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="taskcomplete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="TASKCOMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task-complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="TASK-COMPLETE")
            is True
        )

    def test_tool_arguments_parameter(self) -> None:
        """Test that tool_arguments parameter is accepted but not used."""
        # The tool_arguments parameter should be accepted but doesn't affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="task_complete", tool_arguments={"key": "value"}
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                tool_name="write_file", tool_arguments={"key": "value"}
            )
            is False
        )

    def test_non_completion_finish_reasons(self) -> None:
        """Test that non-completion finish reasons are not detected."""
        # Unknown or invalid finish reasons should not be detected
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="unknown")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="error")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="timeout")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(finish_reason="cancelled")
            is False
        )

    def test_finish_reason_in_choices_array(self) -> None:
        """Test detection of finish_reason in OpenAI-style choices array."""
        # OpenAI format: metadata with choices array
        metadata_with_choices = {
            "choices": [{"finish_reason": "stop"}],
            "other_key": "value",
        }
        # Note: Current implementation only checks top-level finish_reason in metadata
        # This test documents the current behavior - nested finish_reason is not detected
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata=metadata_with_choices
            )
            is False
        )

        # Top-level finish_reason should work
        metadata_top_level = {"finish_reason": "stop", "other_key": "value"}
        assert (
            CompletionSignalDetector.is_completion_signal(metadata=metadata_top_level)
            is True
        )

    def test_edge_case_tool_names(self) -> None:
        """Test edge cases for tool name detection."""
        # Tool name with numbers
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task_complete_v2")
            is False
        )

        # Tool name with prefix
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="my_task_complete")
            is False
        )

        # Tool name with suffix
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="complete_task")
            is False
        )

        # Exact matches only (after normalization)
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(tool_name="taskcomplete")
            is True
        )

    def test_all_completion_tool_variants(self) -> None:
        """Test all defined completion tool names and their variants."""
        completion_tools = [
            "attempt_completion",
            "task_complete",
            "mark_complete",
            "finish_task",
            "complete",
            "done",
        ]

        for tool in completion_tools:
            # Exact match
            assert CompletionSignalDetector.is_completion_signal(tool_name=tool) is True

            # Uppercase
            assert (
                CompletionSignalDetector.is_completion_signal(tool_name=tool.upper())
                is True
            )

            # Mixed case
            assert (
                CompletionSignalDetector.is_completion_signal(
                    tool_name=tool.replace("_", "").title()
                )
                is True
            )

            # Without underscores
            assert (
                CompletionSignalDetector.is_completion_signal(
                    tool_name=tool.replace("_", "")
                )
                is True
            )

    def test_all_finish_reasons(self) -> None:
        """Test all defined finish_reason values."""
        finish_reasons = ["stop", "tool_calls", "length", "end_turn"]

        for reason in finish_reasons:
            # Exact match
            assert (
                CompletionSignalDetector.is_completion_signal(finish_reason=reason)
                is True
            )

            # Uppercase
            assert (
                CompletionSignalDetector.is_completion_signal(
                    finish_reason=reason.upper()
                )
                is True
            )

            # Mixed case
            assert (
                CompletionSignalDetector.is_completion_signal(
                    finish_reason=reason.title()
                )
                is True
            )

    def test_metadata_with_non_dict_value(self) -> None:
        """Test that non-dict metadata is handled gracefully."""
        # Non-dict metadata should not cause errors
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata="not a dict"  # type: ignore
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(metadata=123)  # type: ignore
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                metadata=["list"]  # type: ignore
            )
            is False
        )
