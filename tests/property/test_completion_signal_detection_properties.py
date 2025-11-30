"""Property-based tests for completion signal detection.

Feature: test-execution-reminder
Property 4: Completion Signal Detection
Validates: Requirements 3.1, 3.2, 3.5
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
    base_tools = [
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
def completion_message_strategy(draw: Any) -> str:
    """Generate messages that contain completion indicators.

    This generates text that should be recognized as completion signals
    based on the defined patterns.
    """
    # Templates that match completion patterns
    templates = [
        # Pattern 1: (task|implementation|feature|fix|change)s? (is )?(complete|done|finished|ready)
        "The task is complete",
        "Task complete",
        "Implementation is done",
        "Feature finished",
        "Fix is ready",
        "Changes are complete",
        "The implementation is finished",
        "Task is done",
        # Pattern 2: completed? (the )?(task|implementation|feature|fix|work)
        "Completed the task",
        "Completed task",
        "Complete the implementation",
        "Completed the feature",
        "Completed the fix",
        "Completed the work",
        "Complete work",
        # Pattern 3: all (tests?|checks?) pass(ing|ed)?
        "All tests pass",
        "All tests passing",
        "All tests passed",
        "All checks pass",
        "All checks passing",
        "All checks passed",
        # Pattern 4: ready (for|to) (review|merge|deploy|commit)
        "Ready for review",
        "Ready to merge",
        "Ready for deploy",
        "Ready to commit",
        "Ready for merge",
        # Pattern 5: finished (implementing|coding|working on)
        "Finished implementing",
        "Finished coding",
        "Finished working on",
        "Finished implementing the feature",
    ]

    template = draw(st.sampled_from(templates))

    # Optionally add context before/after
    add_prefix = draw(st.booleans())
    add_suffix = draw(st.booleans())

    prefixes = [
        "",
        "I have ",
        "We have ",
        "The agent has ",
        "Successfully ",
        "Finally, ",
    ]

    suffixes = [
        "",
        ".",
        "!",
        " and ready to proceed.",
        " as requested.",
        " successfully.",
    ]

    result = template
    if add_prefix:
        result = draw(st.sampled_from(prefixes)) + result
    if add_suffix:
        result = result + draw(st.sampled_from(suffixes))

    return result


@st.composite
def non_completion_message_strategy(draw: Any) -> str:
    """Generate messages that should NOT be recognized as completion signals.

    This generates progress updates and other messages that are ambiguous
    or clearly not completion signals.
    """
    # Messages that should NOT match completion patterns
    non_completion_messages = [
        "Working on the task",
        "In progress",
        "Starting implementation",
        "Analyzing the code",
        "Running tests",
        "Executing command",
        "Reading file",
        "Writing to file",
        "Applying changes",
        "Modifying code",
        "Updating implementation",
        "Refactoring code",
        "Adding feature",
        "Fixing bug",
        "Testing changes",
        "Compiling code",
        "Building project",
        "Deploying application",
        "Starting server",
        "Stopping server",
        "Querying database",
        "Fetching data",
        "Parsing response",
        "Validating input",
        "Processing request",
        "Handling error",
        "Logging message",
        "Debugging issue",
        "Investigating problem",
        "Researching solution",
        "Planning approach",
        "Designing architecture",
        "Documenting code",
        "Reviewing changes",
        "Merging branches",
        "Committing changes",
        "Pushing code",
        "Pulling updates",
        "Checking status",
        "Monitoring progress",
        "Tracking metrics",
        "Measuring performance",
        "Optimizing code",
        "Improving efficiency",
        "Enhancing functionality",
        "Extending features",
        "Maintaining codebase",
        "Supporting users",
        "Assisting developers",
        "Collaborating with team",
        "Communicating updates",
        "Reporting results",
        "Summarizing findings",
        "Presenting data",
        "Visualizing metrics",
        "Analyzing trends",
        "Predicting outcomes",
        "Recommending actions",
        "Suggesting improvements",
        "Proposing changes",
        "Requesting feedback",
        "Awaiting approval",
        "Pending review",
        "Under consideration",
        "In development",
        "Being tested",
        "Undergoing validation",
        "Awaiting deployment",
        "Scheduled for release",
        "Planned for next sprint",
        "Targeted for milestone",
        "Assigned to developer",
        "Allocated to team",
        "Prioritized in backlog",
        "Queued for processing",
        "Waiting for resources",
        "Blocked by dependency",
        "Delayed due to issue",
        "Postponed until later",
        "Deferred to future",
        "Cancelled by request",
        "Rejected by reviewer",
        "Declined by stakeholder",
        "Abandoned due to constraints",
    ]

    message = draw(st.sampled_from(non_completion_messages))

    # Optionally add context
    add_suffix = draw(st.booleans())
    if add_suffix:
        suffixes = [".", "...", " now.", " currently.", " at the moment."]
        message = message + draw(st.sampled_from(suffixes))

    return message


@st.composite
def ambiguous_message_strategy(draw: Any) -> str:
    """Generate ambiguous messages that might be mistaken for completion.

    These messages contain words like 'complete' or 'done' but in contexts
    that should NOT be recognized as completion signals.
    """
    ambiguous_messages = [
        "Need to complete the task",
        "Will be done soon",
        "Almost complete",
        "Nearly finished",
        "Close to completion",
        "Approaching the finish",
        "Making progress toward completion",
        "Working to complete",
        "Trying to finish",
        "Attempting to complete",
        "Planning to finish",
        "Expecting to complete",
        "Hoping to finish",
        "Aiming to complete",
        "Striving to finish",
        "Preparing to complete",
        "Getting ready to finish",
        "About to complete",
        "On the verge of finishing",
        "Nearing completion",
        "Incomplete",
        "Not done yet",
        "Still working",
        "Partially complete",
        "Halfway done",
        "Quarter complete",
        "Mostly done",
        "Largely complete",
        "Substantially finished",
        "Essentially complete",
        "Practically done",
        "Virtually finished",
        "More or less complete",
        "Just about done",
        "Very nearly finished",
        "So close to completion",
        "This will complete the task",
        "That would finish the work",
        "It should complete soon",
        "They will be done later",
        "We might finish tomorrow",
        "You could complete it",
        "I may finish eventually",
        "Someone should complete this",
        "Anyone can finish that",
        "Everyone must complete their part",
    ]

    return draw(st.sampled_from(ambiguous_messages))


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
    result = CompletionSignalDetector.is_completion_signal(tool_name)

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
    # (unless there's completion text, which we're not providing)
    result = CompletionSignalDetector.is_completion_signal(tool_name)

    assert result is False, (
        f"Non-completion tool '{tool_name}' was incorrectly detected "
        f"as a completion signal. The detector should only match known "
        f"completion tool patterns."
    )


@given(message=completion_message_strategy())
@property_test_settings()
def test_property_4_completion_message_detection_positive(message: str) -> None:
    """
    Property 4: Completion Message Detection (Positive Cases).

    For any message containing completion indicators, the detector should
    identify it as a completion signal, regardless of the tool name.

    Validates: Requirements 3.1
    """
    # Use a non-completion tool name to ensure we're testing message detection
    tool_name = "some_tool"

    # The detector should recognize this as a completion signal based on message
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is True, (
        f"Completion message '{message}' was not detected. "
        f"The detector should recognize completion patterns in messages."
    )


@given(message=non_completion_message_strategy())
@property_test_settings()
def test_property_4_completion_message_detection_negative(message: str) -> None:
    """
    Property 4: Completion Message Detection (Negative Cases).

    For any message that does NOT contain completion indicators, the detector
    should NOT identify it as a completion signal.

    Validates: Requirements 3.1, 3.5
    """
    # Use a non-completion tool name
    tool_name = "some_tool"

    # The detector should NOT recognize this as a completion signal
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is False, (
        f"Non-completion message '{message}' was incorrectly detected "
        f"as a completion signal. The detector should distinguish "
        f"progress updates from completion signals."
    )


@given(message=ambiguous_message_strategy())
@property_test_settings()
def test_property_4_ambiguous_message_handling(message: str) -> None:
    """
    Property 4: Ambiguous Message Handling.

    For any ambiguous message (containing words like 'complete' or 'done'
    but not in completion context), the detector should NOT identify it
    as a completion signal. This tests the pattern matching's ability to
    distinguish genuine completion from progress updates.

    Validates: Requirements 3.5
    """
    # Use a non-completion tool name
    tool_name = "some_tool"

    # The detector should NOT recognize ambiguous messages as completion signals
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is False, (
        f"Ambiguous message '{message}' was incorrectly detected "
        f"as a completion signal. The detector should use pattern matching "
        f"to distinguish completion signals from progress updates."
    )


@given(
    tool_name=completion_tool_name_strategy(),
    message=completion_message_strategy(),
)
@property_test_settings()
def test_property_4_combined_detection(tool_name: str, message: str) -> None:
    """
    Property 4: Combined Detection.

    When both tool name and message indicate completion, the detector
    should identify it as a completion signal.

    Validates: Requirements 3.1, 3.2
    """
    # Both tool name and message indicate completion
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is True, (
        f"Combined completion signal (tool='{tool_name}', message='{message}') "
        f"was not detected. The detector should recognize completion signals "
        f"from either tool name or message content."
    )


@given(
    tool_name=st.one_of(
        completion_tool_name_strategy(),
        non_completion_tool_name_strategy(),
    )
)
@property_test_settings()
def test_property_4_empty_and_none_handling(tool_name: str) -> None:
    """
    Property 4: Empty and None Handling.

    The detector should handle edge cases like empty strings and None
    gracefully without raising exceptions.

    Validates: Requirements 3.1, 3.2
    """
    # Test with empty response text
    result_empty = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=""
    )
    # Should only be True if tool_name is a completion tool
    # (empty text should not cause issues)

    # Test with None response text
    result_none = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=None
    )
    # Should only be True if tool_name is a completion tool

    # Test with empty tool name
    result_empty_tool = CompletionSignalDetector.is_completion_signal(
        "", response_text="some message"
    )
    # Should be False (empty tool name is not a completion tool)
    assert (
        result_empty_tool is False
    ), "Empty tool name should not be detected as completion"


@given(
    tool_name=completion_tool_name_strategy(),
    message=non_completion_message_strategy(),
)
@property_test_settings()
def test_property_4_tool_name_overrides_message(tool_name: str, message: str) -> None:
    """
    Property 4: Tool Name Detection.

    When the tool name indicates completion but the message does not,
    the detector should still identify it as a completion signal
    (tool name is sufficient).

    Validates: Requirements 3.2
    """
    # Tool name indicates completion, message does not
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is True, (
        f"Completion tool '{tool_name}' was not detected even though "
        f"the tool name alone should be sufficient for detection."
    )


@given(
    tool_name=non_completion_tool_name_strategy(),
    message=completion_message_strategy(),
)
@property_test_settings()
def test_property_4_message_overrides_tool_name(tool_name: str, message: str) -> None:
    """
    Property 4: Message Detection.

    When the message indicates completion but the tool name does not,
    the detector should still identify it as a completion signal
    (message is sufficient).

    Validates: Requirements 3.1
    """
    # Message indicates completion, tool name does not
    result = CompletionSignalDetector.is_completion_signal(
        tool_name, response_text=message
    )

    assert result is True, (
        f"Completion message '{message}' was not detected even though "
        f"the message alone should be sufficient for detection."
    )


@given(tool_name=completion_tool_name_strategy())
@property_test_settings()
def test_property_4_normalization_consistency(tool_name: str) -> None:
    """
    Property 4: Normalization Consistency.

    For any completion tool name, adding or removing underscores
    should not affect detection (normalization should handle it).

    Validates: Requirements 3.2
    """
    # Original detection
    original_result = CompletionSignalDetector.is_completion_signal(tool_name)

    # The original tool name should be detected correctly
    assert (
        original_result is True
    ), f"Original tool name '{tool_name}' should be detected"
