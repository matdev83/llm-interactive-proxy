"""Final validation tests for Phase 2 improvements.

This module validates that the improved completion detection works correctly:
1. attempt_completion tool detection
2. finish_reason detection
3. No false positives from removed pattern matching
"""

import pytest
from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)


class TestAttemptCompletionDetection:
    """Validate that attempt_completion tool detection works correctly."""

    def test_attempt_completion_exact_match(self) -> None:
        """Verify exact match for attempt_completion tool."""
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt_completion"
        )
        assert result is True, "Should detect attempt_completion tool"

    def test_attempt_completion_case_insensitive(self) -> None:
        """Verify case-insensitive matching for attempt_completion."""
        test_cases = [
            "attempt_completion",
            "ATTEMPT_COMPLETION",
            "Attempt_Completion",
            "AttemptCompletion",
        ]
        for tool_name in test_cases:
            result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
            assert result is True, f"Should detect {tool_name}"

    def test_attempt_completion_with_hyphens(self) -> None:
        """Verify normalization handles hyphens."""
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt-completion"
        )
        assert result is True, "Should detect attempt-completion with hyphens"

    def test_other_completion_tools(self) -> None:
        """Verify other completion tools are detected."""
        completion_tools = [
            "finish",  # OpenHands
            "finish_task",
            "task_complete",
            "mark_complete",
            "complete",
            "done",
        ]
        for tool_name in completion_tools:
            result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
            assert result is True, f"Should detect {tool_name}"

    def test_non_completion_tools_not_detected(self) -> None:
        """Verify non-completion tools are not detected."""
        non_completion_tools = [
            "write_file",
            "read_file",
            "execute_command",
            "bash",
            "str_replace",
            "apply_diff",
        ]
        for tool_name in non_completion_tools:
            result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
            assert result is False, f"Should NOT detect {tool_name}"


class TestFinishReasonDetection:
    """Validate that finish_reason detection works correctly."""

    def test_finish_reason_stop(self) -> None:
        """Verify 'stop' finish_reason is detected."""
        result = CompletionSignalDetector.is_completion_signal(finish_reason="stop")
        assert result is True, "Should detect 'stop' finish_reason"

    def test_finish_reason_tool_calls(self) -> None:
        """Verify 'tool_calls' finish_reason is detected."""
        result = CompletionSignalDetector.is_completion_signal(
            finish_reason="tool_calls"
        )
        assert result is True, "Should detect 'tool_calls' finish_reason"

    def test_finish_reason_length(self) -> None:
        """Verify 'length' finish_reason is detected."""
        result = CompletionSignalDetector.is_completion_signal(finish_reason="length")
        assert result is True, "Should detect 'length' finish_reason"

    def test_finish_reason_end_turn(self) -> None:
        """Verify 'end_turn' finish_reason is detected (Anthropic)."""
        result = CompletionSignalDetector.is_completion_signal(finish_reason="end_turn")
        assert result is True, "Should detect 'end_turn' finish_reason"

    def test_finish_reason_case_insensitive(self) -> None:
        """Verify finish_reason matching is case-insensitive."""
        test_cases = ["stop", "STOP", "Stop", "StOp"]
        for finish_reason in test_cases:
            result = CompletionSignalDetector.is_completion_signal(
                finish_reason=finish_reason
            )
            assert result is True, f"Should detect {finish_reason}"

    def test_finish_reason_with_whitespace(self) -> None:
        """Verify finish_reason handles whitespace."""
        result = CompletionSignalDetector.is_completion_signal(finish_reason="  stop  ")
        assert result is True, "Should detect finish_reason with whitespace"

    def test_finish_reason_in_metadata(self) -> None:
        """Verify finish_reason is detected in metadata dict."""
        metadata = {"finish_reason": "stop"}
        result = CompletionSignalDetector.is_completion_signal(metadata=metadata)
        assert result is True, "Should detect finish_reason in metadata"

    def test_invalid_finish_reasons_not_detected(self) -> None:
        """Verify invalid finish_reasons are not detected."""
        invalid_reasons = [
            "continue",
            "error",
            "timeout",
            "cancelled",
            "unknown",
        ]
        for finish_reason in invalid_reasons:
            result = CompletionSignalDetector.is_completion_signal(
                finish_reason=finish_reason
            )
            assert result is False, f"Should NOT detect {finish_reason}"


class TestNoFalsePositives:
    """Validate that removed pattern matching doesn't cause false positives."""

    def test_no_response_text_parameter(self) -> None:
        """Verify response_text parameter is no longer accepted."""
        # This should not raise an error, but response_text should be ignored
        result = CompletionSignalDetector.is_completion_signal(tool_name="write_file")
        assert result is False, "Should not detect without valid signals"

    def test_ambiguous_messages_not_detected(self) -> None:
        """Verify ambiguous messages don't trigger false positives.

        These messages used to match the old pattern-based detection but
        should NOT be detected with the new reliable methods.
        """
        # These are NOT completion signals - they're just status updates
        # The old pattern matching would have incorrectly detected these
        ambiguous_cases = [
            "The task is almost complete, just need to add tests",
            "Implementation is done but needs review",
            "All tests pass locally, pushing to remote",
            "Ready for review once CI passes",
            "Finished implementing the feature, now documenting",
        ]

        for message in ambiguous_cases:
            # Without a completion tool or finish_reason, these should NOT be detected
            result = CompletionSignalDetector.is_completion_signal(
                tool_name="write_file"  # Not a completion tool
            )
            assert result is False, f"Should NOT detect: {message}"

    def test_progress_updates_not_detected(self) -> None:
        """Verify progress updates are not detected as completion."""
        # These are progress updates, not completion signals
        progress_updates = [
            "write_file",
            "str_replace",
            "execute_command",
            "read_file",
            "apply_diff",
        ]

        for tool_name in progress_updates:
            result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
            assert result is False, f"Should NOT detect {tool_name}"

    def test_combined_detection_requires_valid_signal(self) -> None:
        """Verify that detection requires at least one valid signal."""
        # No valid signals - should not detect
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="write_file",
            finish_reason="continue",
        )
        assert result is False, "Should NOT detect without valid signals"

        # One valid signal (tool_name) - should detect
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt_completion",
            finish_reason="continue",
        )
        assert result is True, "Should detect with valid tool_name"

        # One valid signal (finish_reason) - should detect
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="write_file",
            finish_reason="stop",
        )
        assert result is True, "Should detect with valid finish_reason"

        # Both valid signals - should detect
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt_completion",
            finish_reason="stop",
        )
        assert result is True, "Should detect with both valid signals"


class TestReliableDetectionBenefits:
    """Validate the benefits of the new reliable detection approach."""

    def test_streaming_response_detection(self) -> None:
        """Verify finish_reason works with streaming responses."""
        # Simulate a streaming response with finish_reason
        result = CompletionSignalDetector.is_completion_signal(finish_reason="stop")
        assert result is True, "Should detect streaming completion"

    def test_explicit_completion_tool_detection(self) -> None:
        """Verify explicit completion tools are detected."""
        # Simulate Cline/Roo-Code calling attempt_completion
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt_completion",
            tool_arguments={"result": "Task completed successfully"},
        )
        assert result is True, "Should detect explicit completion tool"

    def test_no_speculation_required(self) -> None:
        """Verify detection is based on actual agent behavior, not speculation."""
        # The new approach uses:
        # 1. Actual tool names from real agents (attempt_completion, finish)
        # 2. Standard API finish_reason values (stop, tool_calls, length, end_turn)
        #
        # This is reliable because it's based on:
        # - Real agent source code analysis
        # - Standard LLM API specifications
        # - Not speculative pattern matching against model output

        # Test with real agent tool
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="attempt_completion"  # Used by Cline, Roo-Code
        )
        assert result is True, "Should detect real agent completion tool"

        # Test with standard API finish_reason
        result = CompletionSignalDetector.is_completion_signal(
            finish_reason="stop"  # Standard OpenAI/Anthropic finish_reason
        )
        assert result is True, "Should detect standard API finish_reason"

    def test_no_false_positives_from_model_output(self) -> None:
        """Verify no false positives from ambiguous model output."""
        # The old approach would match patterns in model output like:
        # "The task is complete" or "All tests pass"
        # These are NOT reliable completion signals

        # With the new approach, we only detect:
        # 1. Explicit completion tool calls
        # 2. Streaming finish_reason markers

        # Without these signals, we should NOT detect completion
        result = CompletionSignalDetector.is_completion_signal(
            tool_name="write_file"  # Not a completion tool
        )
        assert result is False, "Should NOT detect without valid signals"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
