"""Property-based tests for state transitions in test execution reminder handler.

Feature: test-execution-reminder
Property 1: File Modification Detection and State Transition
Validates: Requirements 1.1, 1.2, 1.4
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
def execution_command_strategy(draw: Any) -> str:
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


@st.composite
def non_modification_non_test_tool_strategy(draw: Any) -> str:
    """Generate tool names that are neither modifications nor tests."""
    tools = [
        "read_file",
        "list_files",
        "search_files",
        "get_file_info",
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

    return draw(st.sampled_from(tools))


@st.composite
def tool_call_context_strategy(
    draw: Any, tool_name: str, is_shell_command: bool = False
) -> ToolCallContext:
    """Generate a ToolCallContext for testing."""
    session_id = draw(st.text(min_size=1, max_size=50, alphabet=st.characters()))

    if is_shell_command:
        # For shell commands, use bash/execute tool with command argument
        shell_tool = draw(st.sampled_from(["bash", "execute", "shell", "cmd"]))
        tool_arguments = {"command": tool_name}
        actual_tool_name = shell_tool
    else:
        tool_arguments = {}
        actual_tool_name = tool_name

    return ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=actual_tool_name,
        tool_arguments=tool_arguments,
    )


# ============================================================================
# Property Tests for State Transitions
# ============================================================================


@given(
    file_tool=file_modification_tool_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_1_file_modification_marks_dirty(
    file_tool: str, session_id: str
) -> None:
    """
    Property 1: File Modification Detection and State Transition.

    For any file modification tool call, the handler should mark the session
    as dirty when processing the tool call through can_handle.

    Validates: Requirements 1.1, 1.2, 1.4
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Create context for file modification
    context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool,
        tool_arguments={},
    )

    # Process the tool call
    can_handle_result = await handler.can_handle(context)

    # File modification tools should not be handled (return False)
    # but should mark the session as dirty
    assert can_handle_result is False, (
        f"File modification tool '{file_tool}' should not be handled "
        f"(should return False from can_handle)"
    )

    # Verify session is marked as dirty
    state = handler._get_session_state(session_id)
    assert state is not None, f"Session state should exist for session {session_id}"
    assert state.is_dirty is True, (
        f"Session should be marked as dirty after file modification "
        f"with tool '{file_tool}'"
    )
    assert state.modification_count > 0, (
        f"Modification count should be > 0 after file modification "
        f"with tool '{file_tool}'"
    )


@given(
    test_command=execution_command_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_1_test_execution_marks_clean(
    test_command: str, session_id: str
) -> None:
    """
    Property 1: Test Execution Clears Dirty State.

    For any test execution command, the handler should mark the session
    as clean when processing the command through can_handle.

    Validates: Requirements 2.1-2.18
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # First, mark session as dirty
    await handler._mark_session_dirty(session_id)

    # Verify it's dirty
    state_before = handler._get_session_state(session_id)
    assert state_before is not None
    assert state_before.is_dirty is True

    # Create context for test execution (as shell command)
    context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",  # Shell tool
        tool_arguments={"command": test_command},
    )

    # Process the tool call
    can_handle_result = await handler.can_handle(context)

    # Test execution should not be handled (return False)
    # but should mark the session as clean
    assert can_handle_result is False, (
        f"Test execution command '{test_command}' should not be handled "
        f"(should return False from can_handle)"
    )

    # Verify session is marked as clean
    state_after = handler._get_session_state(session_id)
    assert (
        state_after is not None
    ), f"Session state should exist for session {session_id}"
    assert state_after.is_dirty is False, (
        f"Session should be marked as clean after test execution "
        f"with command '{test_command}'"
    )
    assert state_after.modification_count == 0, (
        f"Modification count should be reset to 0 after test execution "
        f"with command '{test_command}'"
    )


@given(
    file_tool=file_modification_tool_strategy(),
    test_command=execution_command_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_1_state_transition_cycle(
    file_tool: str, test_command: str, session_id: str
) -> None:
    """
    Property 1: State Transition Cycle.

    For any session, the state transitions should follow the pattern:
    clean -> dirty (after modification) -> clean (after test) -> dirty (after modification)

    Validates: Requirements 1.1, 1.2, 1.4, 2.1-2.18, 8.2
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Initial state should be clean (no state exists yet)
    state_initial = handler._get_session_state(session_id)
    assert state_initial is None or state_initial.is_dirty is False

    # Step 1: File modification -> dirty
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
    ), "State should be dirty after modification"

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
    assert state_after_test is not None
    assert (
        state_after_test.is_dirty is False
    ), "State should be clean after test execution"

    # Step 3: Another file modification -> dirty again
    await handler.can_handle(context_modify)

    state_after_second_modify = handler._get_session_state(session_id)
    assert state_after_second_modify is not None
    assert (
        state_after_second_modify.is_dirty is True
    ), "State should be dirty again after second modification"


@given(
    non_mod_tool=non_modification_non_test_tool_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_1_non_modification_preserves_state(
    non_mod_tool: str, session_id: str
) -> None:
    """
    Property 1: Non-modification Tools Preserve State.

    For any tool that is neither a file modification nor a test execution,
    the session state should not change when processing the tool call.

    Validates: Requirements 1.1, 1.2
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Get initial state (should be None or clean)
    state_before = handler._get_session_state(session_id)
    initial_dirty = state_before.is_dirty if state_before else False

    # Create context for non-modification tool
    context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=non_mod_tool,
        tool_arguments={},
    )

    # Process the tool call
    await handler.can_handle(context)

    # Verify state hasn't changed
    state_after = handler._get_session_state(session_id)
    final_dirty = state_after.is_dirty if state_after else False

    assert initial_dirty == final_dirty, (
        f"Non-modification tool '{non_mod_tool}' should not change dirty state. "
        f"Before: {initial_dirty}, After: {final_dirty}"
    )


@given(
    modification_count=st.integers(min_value=1, max_value=20),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_1_multiple_modifications_accumulate(
    modification_count: int, session_id: str
) -> None:
    """
    Property 1: Multiple Modifications Accumulate.

    For any number of file modifications, the modification count should
    accumulate correctly and the session should remain dirty.

    Validates: Requirements 1.4
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Perform multiple modifications
    for i in range(modification_count):
        context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        await handler.can_handle(context)

        # Verify state after each modification
        state = handler._get_session_state(session_id)
        assert state is not None
        assert (
            state.is_dirty is True
        ), f"State should be dirty after modification {i + 1}"
        assert (
            state.modification_count == i + 1
        ), f"Modification count should be {i + 1}, got {state.modification_count}"

    # Final verification
    final_state = handler._get_session_state(session_id)
    assert final_state is not None
    assert final_state.modification_count == modification_count
    assert final_state.is_dirty is True
