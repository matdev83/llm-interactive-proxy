"""Property-based tests for state transition cycle in test execution reminder handler.

Feature: test-execution-reminder
Property 14: State Transition Cycle
Validates: Requirements 8.2
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating tool calls
# ============================================================================


@st.composite
def file_modification_tool_strategy(draw: Any) -> str:
    """Generate file modification tool names."""
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

    tool = draw(st.sampled_from(base_tools))

    # Apply random case transformations
    case_transform = draw(st.sampled_from(["lower", "upper", "title", "mixed"]))

    if case_transform == "lower":
        return tool.lower()
    elif case_transform == "upper":
        return tool.upper()
    elif case_transform == "title":
        return tool.title()
    else:  # mixed
        return "".join(c.upper() if draw(st.booleans()) else c.lower() for c in tool)


@st.composite
def test_execution_command_strategy(draw: Any) -> str:
    """Generate test execution commands."""
    commands = [
        "pytest",
        "python -m pytest",
        "py.test",
        "python -m unittest",
        "jest",
        "npm test",
        "npm run test",
        "yarn test",
        "cargo test",
        "go test",
        "mvn test",
        "gradle test",
        "./gradlew test",
        "dotnet test",
        "rspec",
        "rake test",
        "phpunit",
        "composer test",
        "ctest",
        "make test",
        "swift test",
        "sbt test",
        "mix test",
        "flutter test",
        "dart test",
    ]

    return draw(st.sampled_from(commands))


# ============================================================================
# Property Test for State Transition Cycle
# ============================================================================


@given(
    file_tool_1=file_modification_tool_strategy(),
    file_tool_2=file_modification_tool_strategy(),
    test_command=test_execution_command_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_14_state_transition_cycle(
    file_tool_1: str,
    file_tool_2: str,
    test_command: str,
    session_id: str,
) -> None:
    """
    Property 14: State Transition Cycle.

    For any session, if the sequence is: modify file -> run tests -> modify file,
    then the state transitions should be: clean -> dirty -> clean -> dirty.

    This validates that the system correctly transitions back to dirty state
    when files are modified after running tests.

    Feature: test-execution-reminder, Property 14: State Transition Cycle
    Validates: Requirements 8.2
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Initial state: clean (no state exists yet)
    state_initial = handler._get_session_state(session_id)
    is_clean_initial = state_initial is None or state_initial.is_dirty is False
    assert is_clean_initial, "Initial state should be clean"

    # Step 1: First file modification -> dirty
    context_modify_1 = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool_1,
        tool_arguments={},
    )
    await handler.can_handle(context_modify_1)

    state_after_modify_1 = handler._get_session_state(session_id)
    assert (
        state_after_modify_1 is not None
    ), "State should exist after first modification"
    assert (
        state_after_modify_1.is_dirty is True
    ), "State should be dirty after first modification"

    # Step 2: Test execution -> clean
    context_test = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": test_command},
    )
    await handler.can_handle(context_test)

    state_after_test = handler._get_session_state(session_id)
    assert state_after_test is not None, "State should exist after test execution"
    assert (
        state_after_test.is_dirty is False
    ), "State should be clean after test execution"
    assert (
        state_after_test.modification_count == 0
    ), "Modification count should be reset after test execution"

    # Step 3: Second file modification -> dirty again
    context_modify_2 = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool_2,
        tool_arguments={},
    )
    await handler.can_handle(context_modify_2)

    state_after_modify_2 = handler._get_session_state(session_id)
    assert (
        state_after_modify_2 is not None
    ), "State should exist after second modification"
    assert (
        state_after_modify_2.is_dirty is True
    ), "State should be dirty again after second modification (validates Requirement 8.2)"
    assert (
        state_after_modify_2.modification_count > 0
    ), "Modification count should be > 0 after second modification"


@given(
    file_tools=st.lists(
        file_modification_tool_strategy(),
        min_size=2,
        max_size=5,
    ),
    test_commands=st.lists(
        test_execution_command_strategy(),
        min_size=1,
        max_size=3,
    ),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_14_extended_cycle_with_multiple_operations(
    file_tools: list[str],
    test_commands: list[str],
    session_id: str,
) -> None:
    """
    Property 14 Extended: State Transition Cycle with Multiple Operations.

    For any session with multiple modifications and test runs, the state
    should correctly transition between dirty and clean states following
    the pattern: clean -> dirty (after any modification) -> clean (after any test).

    This is an extended version that tests more complex scenarios with
    multiple modifications and test runs.

    Feature: test-execution-reminder, Property 14: State Transition Cycle
    Validates: Requirements 8.2
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Initial state: clean
    state_initial = handler._get_session_state(session_id)
    is_clean_initial = state_initial is None or state_initial.is_dirty is False
    assert is_clean_initial, "Initial state should be clean"

    # Interleave modifications and tests
    for i, file_tool in enumerate(file_tools):
        # Modification -> should be dirty
        context_modify = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name=file_tool,
            tool_arguments={},
        )
        await handler.can_handle(context_modify)

        state_after_modify = handler._get_session_state(session_id)
        assert state_after_modify is not None
        assert (
            state_after_modify.is_dirty is True
        ), f"State should be dirty after modification {i + 1}"

        # Run test (use modulo to cycle through test commands)
        test_command = test_commands[i % len(test_commands)]
        context_test = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": test_command},
        )
        await handler.can_handle(context_test)

        state_after_test = handler._get_session_state(session_id)
        assert state_after_test is not None
        assert (
            state_after_test.is_dirty is False
        ), f"State should be clean after test run {i + 1}"

    # Final modification to ensure we can go back to dirty
    final_tool = file_tools[0]
    context_final_modify = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=final_tool,
        tool_arguments={},
    )
    await handler.can_handle(context_final_modify)

    state_final = handler._get_session_state(session_id)
    assert state_final is not None
    assert (
        state_final.is_dirty is True
    ), "State should be dirty after final modification (validates Requirement 8.2)"


@given(
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_14_clean_to_dirty_transition_after_test(
    session_id: str,
) -> None:
    """
    Property 14 Focused: Clean to Dirty Transition After Test.

    This test specifically validates Requirement 8.2: "WHEN an agent modifies
    files after running tests THEN the system SHALL correctly transition back
    to dirty state."

    Feature: test-execution-reminder, Property 14: State Transition Cycle
    Validates: Requirements 8.2
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Start with a modification to get into dirty state
    context_modify_1 = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="write_file",
        tool_arguments={},
    )
    await handler.can_handle(context_modify_1)

    # Run tests to get into clean state
    context_test = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest"},
    )
    await handler.can_handle(context_test)

    # Verify we're in clean state
    state_after_test = handler._get_session_state(session_id)
    assert state_after_test is not None
    assert state_after_test.is_dirty is False, "State should be clean after test"

    # Now modify files again - this is the key test for Requirement 8.2
    context_modify_2 = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="str_replace",
        tool_arguments={},
    )
    await handler.can_handle(context_modify_2)

    # Verify we correctly transitioned back to dirty state
    state_after_second_modify = handler._get_session_state(session_id)
    assert state_after_second_modify is not None
    assert (
        state_after_second_modify.is_dirty is True
    ), "State MUST transition back to dirty when files are modified after running tests (Requirement 8.2)"
    assert (
        state_after_second_modify.modification_count > 0
    ), "Modification count should be > 0 after modification"
