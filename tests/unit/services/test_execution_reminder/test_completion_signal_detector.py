"""Unit tests for CompletionSignalDetector.

This test suite validates the CompletionSignalDetector's ability to identify
completion signals through explicit completion tool names.
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
            CompletionSignalDetector.is_completion_tool(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="mark_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="finish_task")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="complete") is True
        )
        assert CompletionSignalDetector.is_completion_tool(tool_name="done") is True

        # Case variations should work
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="TASK_COMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="Task_Complete")
            is True
        )
        assert CompletionSignalDetector.is_completion_tool(tool_name="DONE") is True

    def test_non_completion_tool_rejection(self) -> None:
        """Test that non-completion tools are not detected."""
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="write_file")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="read_file")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="execute_command")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="run_tests")
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="pytest") is False
        )

    def test_attempt_completion_tool_detection(self) -> None:
        """Test detection of attempt_completion tool (used by Cline/Roo-Code)."""
        # This is the most common completion tool used by real agents
        assert (
            CompletionSignalDetector.is_completion_tool(
                tool_name="attempt_completion"
            )
            is True
        )

        # Case variations should work
        assert (
            CompletionSignalDetector.is_completion_tool(
                tool_name="ATTEMPT_COMPLETION"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(
                tool_name="Attempt_Completion"
            )
            is True
        )

        # With hyphens instead of underscores
        assert (
            CompletionSignalDetector.is_completion_tool(
                tool_name="attempt-completion"
            )
            is True
        )

    def test_finish_tool_detection(self) -> None:
        """Test detection of finish tool (used by OpenHands/OpenDevin)."""
        # This is the completion tool used by OpenHands (formerly OpenDevin)
        assert CompletionSignalDetector.is_completion_tool(tool_name="finish") is True

        # Case variations should work
        assert CompletionSignalDetector.is_completion_tool(tool_name="FINISH") is True
        assert CompletionSignalDetector.is_completion_tool(tool_name="Finish") is True

    def test_empty_and_none_handling(self) -> None:
        """Test handling of empty strings and None values."""
        # Empty tool name
        assert CompletionSignalDetector.is_completion_tool(tool_name="") is False

        # None tool name (type checking might complain but runtime should handle)
        assert CompletionSignalDetector.is_completion_tool(tool_name=None) is False  # type: ignore

    def test_case_insensitive_tool_matching(self) -> None:
        """Test that tool name matching is case-insensitive."""
        # Tool names
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="TASK_COMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="Task_Complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="task_COMPLETE")
            is True
        )
        assert CompletionSignalDetector.is_completion_tool(tool_name="DONE") is True

    def test_normalization_with_underscores_and_hyphens(self) -> None:
        """Test that underscores and hyphens are normalized in tool names."""
        # These should all be detected as the same tool
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="taskcomplete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="TASKCOMPLETE")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="task-complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="TASK-COMPLETE")
            is True
        )

    def test_edge_case_tool_names(self) -> None:
        """Test edge cases for tool name detection."""
        # Tool name with numbers
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="task_complete_v2")
            is False
        )

        # Tool name with prefix
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="my_task_complete")
            is False
        )

        # Tool name with suffix
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="complete_task")
            is False
        )

        # Exact matches only (after normalization)
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="task_complete")
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_tool(tool_name="taskcomplete")
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
            assert CompletionSignalDetector.is_completion_tool(tool_name=tool) is True

            # Uppercase
            assert (
                CompletionSignalDetector.is_completion_tool(tool_name=tool.upper())
                is True
            )

            # Mixed case
            assert (
                CompletionSignalDetector.is_completion_tool(
                    tool_name=tool.replace("_", "").title()
                )
                is True
            )

            # Without underscores
            assert (
                CompletionSignalDetector.is_completion_tool(
                    tool_name=tool.replace("_", "")
                )
                is True
            )
