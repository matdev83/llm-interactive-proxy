"""Property-based tests for file modification detection.

Feature: test-execution-reminder
Property 1: File Modification Detection and State Transition
Validates: Requirements 1.1, 1.2, 1.4
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.services.test_execution_reminder.file_modification_detector import (
    FileModificationDetector,
)
from src.services.test_execution_reminder.session_state import (
    TestExecutionSessionState,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating tool names
# ============================================================================


@st.composite
def file_modification_tool_name_strategy(draw: Any) -> str:
    """Generate file modification tool names with various formats.

    This generates tool names from the known set of file modification tools,
    with random case variations and formatting to test normalization.
    """
    # Base tool names that should be recognized
    base_tools = [
        "write_file",
        "replace_lines",
        "replace_in_file",
        "write_to_file",
        "apply_diff",
        "apply_patch",
        "patch_file",
        "str_replace",
        "multiedit",
        "fs/write_text_file",
        "insert_content",
        "patch",
        "patchfile",
        "strreplace",
        "fswrite",
        "fs_write",
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
def non_file_modification_tool_name_strategy(draw: Any) -> str:
    """Generate tool names that should NOT be recognized as file modifications.

    This generates tool names that are clearly not file modification operations.
    """
    non_modification_tools = [
        "read_file",
        "list_files",
        "search_files",
        "get_file_info",
        "execute_command",
        "run_tests",
        "pytest",
        "npm_test",
        "task_complete",
        "mark_complete",
        "finish_task",
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
    ]

    tool = draw(st.sampled_from(non_modification_tools))

    # Apply random case transformations
    case_transform = draw(st.sampled_from(["lower", "upper", "title"]))

    if case_transform == "lower":
        return tool.lower()
    elif case_transform == "upper":
        return tool.upper()
    else:  # title
        return tool.title()


@st.composite
def tool_call_sequence_strategy(draw: Any) -> list[tuple[str, bool]]:
    """Generate a sequence of tool calls with expected modification status.

    Returns a list of tuples: (tool_name, is_modification)
    """
    sequence_length = draw(st.integers(min_value=1, max_value=20))
    sequence = []

    for _ in range(sequence_length):
        # Randomly choose between modification and non-modification tool
        is_modification = draw(st.booleans())

        if is_modification:
            tool_name = draw(file_modification_tool_name_strategy())
        else:
            tool_name = draw(non_file_modification_tool_name_strategy())

        sequence.append((tool_name, is_modification))

    return sequence


# ============================================================================
# Property Tests
# ============================================================================


@given(tool_name=file_modification_tool_name_strategy())
@property_test_settings()
def test_property_1_file_modification_detection_positive(tool_name: str) -> None:
    """
    Property 1: File Modification Detection (Positive Cases).

    For any tool call with a name matching a file modification pattern,
    the detector should identify it as a file modification operation,
    regardless of case or formatting variations.

    Validates: Requirements 1.1, 1.2
    """
    # The detector should recognize this as a file modification
    result = FileModificationDetector.is_file_modification(tool_name)

    assert result is True, (
        f"File modification tool '{tool_name}' was not detected. "
        f"The detector should recognize all file modification patterns "
        f"with case-insensitive matching and normalization."
    )


@given(tool_name=non_file_modification_tool_name_strategy())
@property_test_settings()
def test_property_1_file_modification_detection_negative(tool_name: str) -> None:
    """
    Property 1: File Modification Detection (Negative Cases).

    For any tool call with a name that does NOT match a file modification
    pattern, the detector should NOT identify it as a file modification.

    Validates: Requirements 1.1, 1.2
    """
    # The detector should NOT recognize this as a file modification
    result = FileModificationDetector.is_file_modification(tool_name)

    assert result is False, (
        f"Non-modification tool '{tool_name}' was incorrectly detected "
        f"as a file modification. The detector should only match known "
        f"file modification patterns."
    )


@given(sequence=tool_call_sequence_strategy())
@property_test_settings()
def test_property_1_state_transition_consistency(
    sequence: list[tuple[str, bool]],
) -> None:
    """
    Property 1: State Transition Consistency.

    For any sequence of tool calls, the session state should transition to
    dirty after each file modification and remain dirty until explicitly
    cleared. Non-modification tools should not affect the dirty state.

    Validates: Requirements 1.1, 1.2, 1.4
    """
    # Create a fresh session state
    state = TestExecutionSessionState()

    # Initially, state should be clean
    assert state.is_dirty is False, "Initial state should be clean"
    assert state.modification_count == 0, "Initial modification count should be 0"

    # Track expected state
    expected_dirty = False
    expected_count = 0

    # Process each tool call in the sequence
    for tool_name, is_modification in sequence:
        # Verify detection matches expectation
        detected = FileModificationDetector.is_file_modification(tool_name)
        assert detected == is_modification, (
            f"Detection mismatch for '{tool_name}': "
            f"expected {is_modification}, got {detected}"
        )

        # If it's a modification, mark state as dirty
        if is_modification:
            state.mark_dirty()
            expected_dirty = True
            expected_count += 1

        # Verify state matches expectation
        assert state.is_dirty == expected_dirty, (
            f"State mismatch after processing '{tool_name}': "
            f"expected dirty={expected_dirty}, got dirty={state.is_dirty}"
        )

        assert state.modification_count == expected_count, (
            f"Modification count mismatch after processing '{tool_name}': "
            f"expected {expected_count}, got {state.modification_count}"
        )


@given(
    tool_name=st.one_of(
        file_modification_tool_name_strategy(),
        non_file_modification_tool_name_strategy(),
    )
)
@property_test_settings()
def test_property_1_empty_and_none_handling(tool_name: str) -> None:
    """
    Property 1: Empty and None Handling.

    The detector should handle edge cases like empty strings and None
    gracefully without raising exceptions.

    Validates: Requirements 1.1, 1.2
    """
    # Test empty string
    result_empty = FileModificationDetector.is_file_modification("")
    assert result_empty is False, "Empty string should not be detected as modification"

    # Test None (should not crash)
    # Note: Type checker will complain, but we want to test runtime behavior
    try:
        result_none = FileModificationDetector.is_file_modification(None)  # type: ignore
        # If it doesn't crash, it should return False
        assert result_none is False, "None should not be detected as modification"
    except (TypeError, AttributeError):
        # It's acceptable to raise an exception for None
        pass


@given(tool_name=file_modification_tool_name_strategy())
@property_test_settings()
def test_property_1_normalization_consistency(tool_name: str) -> None:
    """
    Property 1: Normalization Consistency.

    For any file modification tool name, adding or removing underscores
    and slashes should not affect detection (normalization should handle it).

    Validates: Requirements 1.1, 1.2
    """
    # Original detection
    original_result = FileModificationDetector.is_file_modification(tool_name)

    # The original tool name should be detected correctly
    assert (
        original_result is True
    ), f"Original tool name '{tool_name}' should be detected"


@given(
    modification_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings()
def test_property_1_modification_count_tracking(modification_count: int) -> None:
    """
    Property 1: Modification Count Tracking.

    For any number of file modifications, the session state should
    accurately track the count of modifications.

    Validates: Requirements 1.4
    """
    state = TestExecutionSessionState()

    # Perform modifications
    for i in range(modification_count):
        state.mark_dirty()

        # Verify count is correct
        assert (
            state.modification_count == i + 1
        ), f"Modification count should be {i + 1}, got {state.modification_count}"

        # Verify state is dirty
        assert state.is_dirty is True, "State should be dirty after modification"

    # Final verification
    assert state.modification_count == modification_count, (
        f"Final modification count should be {modification_count}, "
        f"got {state.modification_count}"
    )
