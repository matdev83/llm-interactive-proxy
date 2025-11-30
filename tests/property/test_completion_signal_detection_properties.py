"""Property-based tests for completion signal detection.

Feature: test-execution-reminder
Property 4: Completion Signal Detection
Validates: Requirements 3.1, 3.2
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.services.test_execution_reminder.completion_signal_detector import (
    CompletionSignalDetector,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating completion signals
# ============================================================================


@st.composite
def completion_tool_name_strategy(draw: Any) -> str:
    """Generate completion tool names with various formats.

    This generates tool names from the known set of completion tools,
    with random case variations and formatting to test normalization.
    """
    # Base tool names that should be recognized as completion signals
    # Including attempt_completion which is used by Cline and Roo-Code
    base_tools = [
        "attempt_completion",
        "task_complete",
        "mark_complete",
        "finish_task",
        "complete",
        "done",
    ]

    # Pick a base tool
    base_tool = draw(st.sampled_from(base_tools))

    # Apply random case transformations
    case_transform = draw(st.sampled_from(["lower", "upper", "title", "mixed"]))

    if case_transform == "lower":
        return base_tool.lower()
    elif case_transform == "upper":
        return base_tool.upper()
    elif case_transform == "title":
        return base_tool.title()
    else:  # mixed
        # Randomly capitalize each character
        return "".join(
            c.upper() if draw(st.booleans()) else c.lower() for c in base_tool
        )


@st.composite
def non_completion_tool_name_strategy(draw: Any) -> str:
    """Generate tool names that should NOT be recognized as completion signals.

    This generates tool names that are clearly not completion operations.
    """
    non_completion_tools = [
        "write_file",
        "read_file",
        "list_files",
        "search_files",
        "execute_command",
        "run_tests",
        "pytest",
        "npm_test",
        "analyze_code",
        "lint_code",
        "format_code",
        "compile_code",
        "build_project",
        "deploy_app",
        "start_server",
        "stop_server",
        "query_database",
        "fetch_data",
        "send_request",
        "parse_json",
        "validate_schema",
        "str_replace",
        "apply_diff",
        "patch_file",
    ]

    tool = draw(st.sampled_from(non_completion_tools))

    # Apply random case transformations
    case_transform = draw(st.sampled_from(["lower", "upper", "title"]))

    if case_transform == "lower":
        return tool.lower()
    elif case_transform == "upper":
        return tool.upper()
    else:  # title
        return tool.title()


@st.composite
def finish_reason_strategy(draw: Any) -> str:
    """Generate valid finish_reason values.

    This generates finish_reason values that should be recognized as
    completion signals, with random case variations.
    """
    # Valid finish reasons from OpenAI/Anthropic APIs
    base_reasons = [
        "stop",
        "tool_calls",
        "length",
        "end_turn",
    ]

    # Pick a base reason
    base_reason = draw(st.sampled_from(base_reasons))

    # Apply random case transformations
    case_transform = draw(st.sampled_from(["lower", "upper", "title"]))

    if case_transform == "lower":
        return base_reason.lower()
    elif case_transform == "upper":
        return base_reason.upper()
    else:  # title
        return base_reason.title()


@st.composite
def non_finish_reason_strategy(draw: Any) -> str:
    """Generate invalid finish_reason values.

    This generates finish_reason values that should NOT be recognized
    as completion signals.
    """
    # Invalid finish reasons that should not trigger completion
    invalid_reasons = [
        "error",
        "timeout",
        "cancelled",
        "interrupted",
        "pending",
        "processing",
        "waiting",
        "streaming",
        "partial",
        "incomplete",
        "failed",
        "aborted",
        "rejected",
        "invalid",
        "unknown",
        "",
        "null",
        "none",
    ]

    return draw(st.sampled_from(invalid_reasons))


# ============================================================================
# Property Tests
# ============================================================================


@given(tool_name=completion_tool_name_strategy())
@property_test_settings()
def test_property_4_completion_tool_detection_positive(tool_name: str) -> None:
    """
    Property 4: Completion Tool Detection (Positive Cases).

    For any tool call with a name matching a completion tool pattern,
    the detector should identify it as a completion signal, regardless
    of case or formatting variations.

    Validates: Requirements 3.2
    """
    # The detector should recognize this as a completion signal
    result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)

    assert result is True, (
        f"Completion tool '{tool_name}' was not detected. "
        f"The detector should recognize all completion tool patterns "
        f"with case-insensitive matching and normalization."
    )


@given(tool_name=non_completion_tool_name_strategy())
@property_test_settings()
def test_property_4_completion_tool_detection_negative(tool_name: str) -> None:
    """
    Property 4: Completion Tool Detection (Negative Cases).

    For any tool call with a name that does NOT match a completion tool
    pattern, the detector should NOT identify it as a completion signal
    based on tool name alone.

    Validates: Requirements 3.2
    """
    # The detector should NOT recognize this as a completion signal
    result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)

    assert result is False, (
        f"Non-completion tool '{tool_name}' was incorrectly detected "
        f"as a completion signal. The detector should only match known "
        f"completion tool patterns."
    )


@given(finish_reason=finish_reason_strategy())
@property_test_settings()
def test_property_4_finish_reason_detection_positive(finish_reason: str) -> None:
    """
    Property 4: Finish Reason Detection (Positive Cases).

    For any valid finish_reason value, the detector should identify it
    as a completion signal, regardless of case variations.

    Validates: Requirements 3.1
    """
    # The detector should recognize this as a completion signal
    result = CompletionSignalDetector.is_completion_signal(finish_reason=finish_reason)

    assert result is True, (
        f"Valid finish_reason '{finish_reason}' was not detected. "
        f"The detector should recognize all valid finish_reason values "
        f"with case-insensitive matching."
    )


@given(finish_reason=non_finish_reason_strategy())
@property_test_settings()
def test_property_4_finish_reason_detection_negative(finish_reason: str) -> None:
    """
    Property 4: Finish Reason Detection (Negative Cases).

    For any invalid finish_reason value, the detector should NOT identify
    it as a completion signal.

    Validates: Requirements 3.1
    """
    # The detector should NOT recognize this as a completion signal
    result = CompletionSignalDetector.is_completion_signal(finish_reason=finish_reason)

    assert result is False, (
        f"Invalid finish_reason '{finish_reason}' was incorrectly detected "
        f"as a completion signal. The detector should only match known "
        f"finish_reason values."
    )


@given(finish_reason=finish_reason_strategy())
@property_test_settings()
def test_property_4_finish_reason_in_metadata(finish_reason: str) -> None:
    """
    Property 4: Finish Reason in Metadata.

    For any valid finish_reason value in metadata, the detector should
    identify it as a completion signal.

    Validates: Requirements 3.1
    """
    # The detector should recognize finish_reason in metadata
    metadata = {"finish_reason": finish_reason}
    result = CompletionSignalDetector.is_completion_signal(metadata=metadata)

    assert result is True, (
        f"Valid finish_reason '{finish_reason}' in metadata was not detected. "
        f"The detector should check metadata for finish_reason values."
    )


@given(
    tool_name=completion_tool_name_strategy(),
    finish_reason=finish_reason_strategy(),
)
@property_test_settings()
def test_property_4_combined_tool_and_finish_reason(
    tool_name: str, finish_reason: str
) -> None:
    """
    Property 4: Combined Tool Name and Finish Reason.

    When both tool name and finish_reason indicate completion, the detector
    should identify it as a completion signal.

    Validates: Requirements 3.1, 3.2
    """
    # Both tool name and finish_reason indicate completion
    result = CompletionSignalDetector.is_completion_signal(
        tool_name=tool_name, finish_reason=finish_reason
    )

    assert result is True, (
        f"Combined completion signal (tool='{tool_name}', "
        f"finish_reason='{finish_reason}') was not detected. "
        f"The detector should recognize completion signals from either "
        f"tool name or finish_reason."
    )


@given(
    tool_name=non_completion_tool_name_strategy(),
    finish_reason=non_finish_reason_strategy(),
)
@property_test_settings()
def test_property_4_no_completion_signals(tool_name: str, finish_reason: str) -> None:
    """
    Property 4: No Completion Signals.

    When neither tool name nor finish_reason indicate completion, the
    detector should NOT identify it as a completion signal.

    Validates: Requirements 3.1, 3.2
    """
    # Neither tool name nor finish_reason indicate completion
    result = CompletionSignalDetector.is_completion_signal(
        tool_name=tool_name, finish_reason=finish_reason
    )

    assert result is False, (
        f"Non-completion signals (tool='{tool_name}', "
        f"finish_reason='{finish_reason}') were incorrectly detected "
        f"as completion. The detector should only match known patterns."
    )


@given(tool_name=completion_tool_name_strategy())
@property_test_settings()
def test_property_4_tool_name_with_underscores_and_hyphens(tool_name: str) -> None:
    """
    Property 4: Tool Name Normalization.

    For any completion tool name, variations with underscores and hyphens
    should be detected correctly due to normalization.

    Validates: Requirements 3.2
    """
    # Original detection
    original_result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
    assert (
        original_result is True
    ), f"Original tool name '{tool_name}' should be detected"

    # Add hyphens instead of underscores
    hyphenated = tool_name.replace("_", "-")
    hyphenated_result = CompletionSignalDetector.is_completion_signal(
        tool_name=hyphenated
    )
    assert (
        hyphenated_result is True
    ), f"Hyphenated tool name '{hyphenated}' should be detected"

    # Remove all separators
    no_separators = tool_name.replace("_", "").replace("-", "")
    no_sep_result = CompletionSignalDetector.is_completion_signal(
        tool_name=no_separators
    )
    assert (
        no_sep_result is True
    ), f"Tool name without separators '{no_separators}' should be detected"


@given(
    tool_name=st.one_of(
        completion_tool_name_strategy(),
        non_completion_tool_name_strategy(),
        st.just(""),
        st.none(),
    )
)
@property_test_settings()
def test_property_4_empty_and_none_handling(tool_name: str | None) -> None:
    """
    Property 4: Empty and None Handling.

    The detector should handle edge cases like empty strings and None
    gracefully without raising exceptions.

    Validates: Requirements 3.1, 3.2
    """
    # Test with None finish_reason
    CompletionSignalDetector.is_completion_signal(
        tool_name=tool_name, finish_reason=None
    )
    # Should only be True if tool_name is a completion tool

    # Test with empty finish_reason
    CompletionSignalDetector.is_completion_signal(tool_name=tool_name, finish_reason="")
    # Should only be True if tool_name is a completion tool

    # Test with empty metadata
    CompletionSignalDetector.is_completion_signal(tool_name=tool_name, metadata={})
    # Should only be True if tool_name is a completion tool

    # Test with None metadata
    CompletionSignalDetector.is_completion_signal(tool_name=tool_name, metadata=None)
    # Should only be True if tool_name is a completion tool

    # No assertions needed - just verify no exceptions are raised


@given(tool_name=completion_tool_name_strategy())
@property_test_settings()
def test_property_4_attempt_completion_detection(tool_name: str) -> None:
    """
    Property 4: Attempt Completion Tool Detection.

    The detector should specifically recognize 'attempt_completion' which
    is used by Cline and Roo-Code agents.

    Validates: Requirements 3.2
    """
    # Test the specific attempt_completion tool
    if "attempt" in tool_name.lower() and "completion" in tool_name.lower():
        result = CompletionSignalDetector.is_completion_signal(tool_name=tool_name)
        assert result is True, (
            f"attempt_completion variant '{tool_name}' should be detected "
            f"as it's used by Cline and Roo-Code agents"
        )
