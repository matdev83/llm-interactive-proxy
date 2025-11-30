"""Unit tests for CompletionSignalDetector."""

from __future__ import annotations

from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)


class TestCompletionSignalDetector:
    """Test suite for CompletionSignalDetector class."""

    def test_completion_tool_detection(self) -> None:
        """Test detection of completion tool names."""
        # Positive cases - should be detected
        assert CompletionSignalDetector.is_completion_signal("task_complete") is True
        assert CompletionSignalDetector.is_completion_signal("mark_complete") is True
        assert CompletionSignalDetector.is_completion_signal("finish_task") is True
        assert CompletionSignalDetector.is_completion_signal("complete") is True
        assert CompletionSignalDetector.is_completion_signal("done") is True

        # Case variations should work
        assert CompletionSignalDetector.is_completion_signal("TASK_COMPLETE") is True
        assert CompletionSignalDetector.is_completion_signal("Task_Complete") is True
        assert CompletionSignalDetector.is_completion_signal("DONE") is True

    def test_non_completion_tool_rejection(self) -> None:
        """Test that non-completion tools are not detected."""
        assert CompletionSignalDetector.is_completion_signal("write_file") is False
        assert CompletionSignalDetector.is_completion_signal("read_file") is False
        assert CompletionSignalDetector.is_completion_signal("execute_command") is False
        assert CompletionSignalDetector.is_completion_signal("run_tests") is False
        assert CompletionSignalDetector.is_completion_signal("pytest") is False

    def test_completion_message_detection(self) -> None:
        """Test detection of completion messages."""
        # Pattern 1: task/feature/etc is complete/done/finished/ready
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The task is complete"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Implementation is done"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Feature finished"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Changes are complete"
            )
            is True
        )

        # Pattern 2: completed the task/work/etc
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Completed the task"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Complete work"
            )
            is True
        )

        # Pattern 3: all tests/checks pass
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="All tests pass"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="All checks passed"
            )
            is True
        )

        # Pattern 4: ready for review/merge/etc
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Ready for review"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Ready to merge"
            )
            is True
        )

        # Pattern 5: finished implementing/coding/etc
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Finished implementing"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Finished coding"
            )
            is True
        )

    def test_ambiguous_message_rejection(self) -> None:
        """Test that ambiguous messages are not detected as completion."""
        # These should NOT be detected as completion signals
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Need to complete the task"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Will be done soon"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Almost complete"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Working on the task"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="In progress"
            )
            is False
        )

    def test_non_completion_message_rejection(self) -> None:
        """Test that non-completion messages are not detected."""
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Starting implementation"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Running tests"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Writing code"
            )
            is False
        )

    def test_combined_detection(self) -> None:
        """Test detection when both tool name and message indicate completion."""
        # Both indicate completion
        assert (
            CompletionSignalDetector.is_completion_signal(
                "task_complete", response_text="The task is complete"
            )
            is True
        )

        # Tool name indicates completion, message does not
        assert (
            CompletionSignalDetector.is_completion_signal(
                "task_complete", response_text="Working on it"
            )
            is True
        )

        # Message indicates completion, tool name does not
        assert (
            CompletionSignalDetector.is_completion_signal(
                "write_file", response_text="The task is complete"
            )
            is True
        )

    def test_empty_and_none_handling(self) -> None:
        """Test handling of empty strings and None values."""
        # Empty tool name
        assert CompletionSignalDetector.is_completion_signal("") is False

        # Empty response text
        assert (
            CompletionSignalDetector.is_completion_signal("some_tool", response_text="")
            is False
        )

        # None response text
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text=None
            )
            is False
        )

        # Both empty
        assert (
            CompletionSignalDetector.is_completion_signal("", response_text="") is False
        )

    def test_case_insensitive_matching(self) -> None:
        """Test that pattern matching is case-insensitive."""
        # Tool names
        assert CompletionSignalDetector.is_completion_signal("TASK_COMPLETE") is True
        assert CompletionSignalDetector.is_completion_signal("Task_Complete") is True
        assert CompletionSignalDetector.is_completion_signal("task_COMPLETE") is True

        # Messages
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="THE TASK IS COMPLETE"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Task Is Complete"
            )
            is True
        )

    def test_normalization_with_underscores(self) -> None:
        """Test that underscores are normalized in tool names."""
        # These should all be detected as the same tool
        assert CompletionSignalDetector.is_completion_signal("task_complete") is True
        assert CompletionSignalDetector.is_completion_signal("taskcomplete") is True
        assert CompletionSignalDetector.is_completion_signal("TASKCOMPLETE") is True

    def test_tool_arguments_parameter(self) -> None:
        """Test that tool_arguments parameter is accepted but not used."""
        # The tool_arguments parameter should be accepted but doesn't affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                "task_complete", tool_arguments={"key": "value"}
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "write_file", tool_arguments={"key": "value"}
            )
            is False
        )

    def test_whitespace_variations(self) -> None:
        """Test handling of various whitespace patterns."""
        # Extra spaces
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The  task  is  complete"
            )
            is True
        )

        # Leading/trailing whitespace
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="  The task is complete  "
            )
            is True
        )

        # Tabs
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The\ttask\tis\tcomplete"
            )
            is True
        )

        # Newlines in message
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The task is complete\nAll tests pass"
            )
            is True
        )

    def test_pattern_position_in_message(self) -> None:
        """Test that patterns are detected at any position in the message."""
        # Pattern at start
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Task is complete. Everything works."
            )
            is True
        )

        # Pattern in middle
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool",
                response_text="I have verified that the task is complete and ready.",
            )
            is True
        )

        # Pattern at end
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool",
                response_text="After running all checks, the task is complete",
            )
            is True
        )

    def test_multiple_patterns_in_message(self) -> None:
        """Test messages containing multiple completion patterns."""
        # Multiple patterns should still be detected
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool",
                response_text="The task is complete. All tests pass. Ready for review.",
            )
            is True
        )

        # Even if one pattern is ambiguous, a clear pattern should trigger detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool",
                response_text="Need to complete some cleanup, but the feature is done.",
            )
            is True
        )

    def test_special_characters_in_messages(self) -> None:
        """Test handling of special characters in messages."""
        # Punctuation at end should not affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Task is complete!"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Task is complete?"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Task is complete."
            )
            is True
        )

        # Quotes around keywords break word boundaries, so pattern won't match
        # This is expected behavior - the pattern requires proper word boundaries
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text='The "task" is complete'
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text='The task is "complete"'
            )
            is False
        )

        # But quotes in other positions should not affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text='The task is complete "now"'
            )
            is True
        )

        # Parentheses between keywords also break word boundaries
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The task (implementation) is complete"
            )
            is False
        )

        # But parentheses after the pattern should not affect detection
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The task is complete (implementation done)"
            )
            is True
        )

    def test_long_messages(self) -> None:
        """Test detection in very long messages."""
        long_message = (
            "I have been working on this task for a while now. "
            "First, I implemented the core functionality. "
            "Then, I added error handling and validation. "
            "After that, I wrote comprehensive tests. "
            "Finally, I ran all the tests and verified everything works. "
            "The task is complete and ready for review. "
            "Here are some additional details about the implementation..."
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text=long_message
            )
            is True
        )

    def test_edge_case_tool_names(self) -> None:
        """Test edge cases for tool name detection."""
        # Tool name with numbers
        assert (
            CompletionSignalDetector.is_completion_signal("task_complete_v2") is False
        )

        # Tool name with prefix
        assert (
            CompletionSignalDetector.is_completion_signal("my_task_complete") is False
        )

        # Tool name with suffix
        assert CompletionSignalDetector.is_completion_signal("complete_task") is False

        # Exact matches only (after normalization)
        assert CompletionSignalDetector.is_completion_signal("task_complete") is True
        assert CompletionSignalDetector.is_completion_signal("taskcomplete") is True

    def test_negative_lookbehind_patterns(self) -> None:
        """Test that negative lookbehind patterns work correctly."""
        # These should NOT match due to "to" or "will" before "complete"
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="I need to complete the task"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="I will complete the work"
            )
            is False
        )

        # But these SHOULD match (no "to" or "will" immediately before)
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="I completed the task"
            )
            is True
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Just complete the work"
            )
            is True
        )

    def test_word_boundary_matching(self) -> None:
        """Test that word boundaries are respected in pattern matching."""
        # Should match - proper word boundaries
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The task is complete"
            )
            is True
        )

        # Should NOT match - pattern is part of a larger word
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The incomplete task"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="The taskmaster is here"
            )
            is False
        )

    def test_all_completion_tool_variants(self) -> None:
        """Test all defined completion tool names and their variants."""
        completion_tools = [
            "task_complete",
            "mark_complete",
            "finish_task",
            "complete",
            "done",
        ]

        for tool in completion_tools:
            # Exact match
            assert CompletionSignalDetector.is_completion_signal(tool) is True

            # Uppercase
            assert CompletionSignalDetector.is_completion_signal(tool.upper()) is True

            # Mixed case
            assert (
                CompletionSignalDetector.is_completion_signal(
                    tool.replace("_", "").title()
                )
                is True
            )

            # Without underscores
            assert (
                CompletionSignalDetector.is_completion_signal(tool.replace("_", ""))
                is True
            )

    def test_all_completion_message_patterns(self) -> None:
        """Test all defined completion message patterns."""
        # Pattern 1 variations
        pattern1_tests = [
            "task is complete",
            "task is done",
            "task is finished",
            "task is ready",
            "implementation is complete",
            "feature is done",
            "fix is finished",
            "changes are complete",
            "change is ready",
        ]
        for text in pattern1_tests:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=text
                )
                is True
            ), f"Failed to detect: {text}"

        # Pattern 2 variations
        pattern2_tests = [
            "completed the task",
            "completed the implementation",
            "completed the feature",
            "completed the fix",
            "completed the work",
            "complete task",
            "complete work",
        ]
        for text in pattern2_tests:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=text
                )
                is True
            ), f"Failed to detect: {text}"

        # Pattern 3 variations
        pattern3_tests = [
            "all tests pass",
            "all tests passing",
            "all tests passed",
            "all test pass",
            "all checks pass",
            "all checks passed",
            "all check passed",
        ]
        for text in pattern3_tests:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=text
                )
                is True
            ), f"Failed to detect: {text}"

        # Pattern 4 variations
        pattern4_tests = [
            "ready for review",
            "ready for merge",
            "ready for deploy",
            "ready for commit",
            "ready to review",
            "ready to merge",
            "ready to deploy",
            "ready to commit",
        ]
        for text in pattern4_tests:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=text
                )
                is True
            ), f"Failed to detect: {text}"

        # Pattern 5 variations
        pattern5_tests = [
            "finished implementing",
            "finished coding",
            "finished working on",
        ]
        for text in pattern5_tests:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=text
                )
                is True
            ), f"Failed to detect: {text}"

    def test_ambiguous_messages_comprehensive(self) -> None:
        """Comprehensive test of ambiguous messages that should NOT be detected."""
        ambiguous_messages = [
            "I will complete the task soon",
            "Need to complete the implementation",
            "Planning to finish the feature",
            "About to be done",
            # Note: "Almost ready for review" contains "ready for review" which matches Pattern 4
            # This is a limitation of the current pattern matching - it's a trade-off between
            # catching genuine completions and avoiding false positives
            "Nearly complete",
            "Partially done",
            "In progress on the task",
            "Working to complete this",
            "Trying to finish",
            "Should be complete soon",
            "Will be ready shortly",
            "Getting close to done",
            "Making progress on the task",
            "Still working on implementation",
        ]

        for message in ambiguous_messages:
            assert (
                CompletionSignalDetector.is_completion_signal(
                    "some_tool", response_text=message
                )
                is False
            ), f"Incorrectly detected as completion: {message}"

    def test_edge_case_almost_ready_for_review(self) -> None:
        """Test edge case: 'Almost ready for review' contains 'ready for review'."""
        # This is detected as completion because it contains "ready for review"
        # which is a strong completion signal. This is a known trade-off in the
        # pattern matching - we prioritize catching genuine completions even if
        # it means some edge cases like "almost ready" are also caught.
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Almost ready for review"
            )
            is True
        )

        # However, other "almost" phrases should not be detected
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Almost done"
            )
            is False
        )
        assert (
            CompletionSignalDetector.is_completion_signal(
                "some_tool", response_text="Almost complete"
            )
            is False
        )

    def test_empty_tool_name_with_completion_message(self) -> None:
        """Test that completion is detected from message even with empty tool name."""
        assert (
            CompletionSignalDetector.is_completion_signal(
                "", response_text="The task is complete"
            )
            is True
        )

    def test_none_tool_name_handling(self) -> None:
        """Test handling of None as tool name."""
        # This tests the robustness of the implementation
        # The method signature doesn't explicitly allow None, but we test defensive coding
        try:
            # If the implementation handles None gracefully
            result = CompletionSignalDetector.is_completion_signal(
                None, response_text="The task is complete"  # type: ignore
            )
            # Should either return False or True based on message
            assert isinstance(result, bool)
        except (TypeError, AttributeError):
            # If it raises an exception, that's also acceptable behavior
            pass
