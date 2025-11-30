"""Property-based tests for clean state preservation in test execution reminder handler.

Feature: test-execution-reminder
Property 3: Clean State Preservation
Validates: Requirements 2.16
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
def non_modification_tool_strategy(draw: Any) -> str:
    """Generate tool names that are not file modifications."""
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
        "execute_command",
        "run_script",
        "check_status",
        "monitor_logs",
        "inspect_data",
    ]

    return draw(st.sampled_from(tools))


# ============================================================================
# Property Tests for Clean State Preservation
# ============================================================================


@given(
    test_command=execution_command_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_test_execution_in_clean_state_remains_clean(
    test_command: str, session_id: str
) -> None:
    """
    Property 3: Clean State Preservation - Test Execution.

    For any session in clean state, if a test execution command is processed,
    the session state should remain clean.

    Validates: Requirements 2.16
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Ensure session starts clean (no state = clean)
    state_before = handler._get_session_state(session_id)
    assert state_before is None or state_before.is_dirty is False

    # Create context for test execution
    context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": test_command},
    )

    # Process the test execution
    can_handle_result = await handler.can_handle(context)

    # Should not be handled
    assert can_handle_result is False

    # Verify state remains clean
    state_after = handler._get_session_state(session_id)
    assert state_after is not None, "State should exist after test execution"
    assert state_after.is_dirty is False, (
        f"Session should remain clean after test execution in clean state. "
        f"Command: '{test_command}'"
    )
    assert state_after.modification_count == 0, (
        f"Modification count should remain 0 after test execution in clean state. "
        f"Command: '{test_command}'"
    )


@given(
    non_mod_tool=non_modification_tool_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_non_modification_in_clean_state_remains_clean(
    non_mod_tool: str, session_id: str
) -> None:
    """
    Property 3: Clean State Preservation - Non-modification Tools.

    For any session in clean state, if a non-modification tool is processed,
    the session state should remain clean.

    Validates: Requirements 2.16
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Ensure session starts clean (no state = clean)
    state_before = handler._get_session_state(session_id)
    assert state_before is None or state_before.is_dirty is False

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
    can_handle_result = await handler.can_handle(context)

    # Should not be handled
    assert can_handle_result is False

    # Verify state remains clean (or still doesn't exist)
    state_after = handler._get_session_state(session_id)
    if state_after is not None:
        assert state_after.is_dirty is False, (
            f"Session should remain clean after non-modification tool in clean state. "
            f"Tool: '{non_mod_tool}'"
        )
        assert state_after.modification_count == 0, (
            f"Modification count should remain 0 after non-modification tool in clean state. "
            f"Tool: '{non_mod_tool}'"
        )


@given(
    test_commands=st.lists(execution_command_strategy(), min_size=1, max_size=10),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_multiple_test_runs_maintain_clean_state(
    test_commands: list[str], session_id: str
) -> None:
    """
    Property 3: Multiple Test Runs Maintain Clean State.

    For any session in clean state, if multiple test execution commands are
    processed in succession, the state should remain clean throughout.

    Validates: Requirements 2.16, 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Process each test command
    for i, test_command in enumerate(test_commands):
        context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": test_command},
        )

        # Process the test execution
        can_handle_result = await handler.can_handle(context)

        # Should not be handled
        assert can_handle_result is False

        # Verify state remains clean after each test
        state = handler._get_session_state(session_id)
        assert state is not None, f"State should exist after test execution {i + 1}"
        assert state.is_dirty is False, (
            f"Session should remain clean after test execution {i + 1}. "
            f"Command: '{test_command}'"
        )
        assert state.modification_count == 0, (
            f"Modification count should remain 0 after test execution {i + 1}. "
            f"Command: '{test_command}'"
        )


@given(
    non_mod_tools=st.lists(non_modification_tool_strategy(), min_size=1, max_size=10),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_multiple_non_modifications_maintain_clean_state(
    non_mod_tools: list[str], session_id: str
) -> None:
    """
    Property 3: Multiple Non-modifications Maintain Clean State.

    For any session in clean state, if multiple non-modification tools are
    processed in succession, the state should remain clean throughout.

    Validates: Requirements 2.16
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Process each non-modification tool
    for i, tool_name in enumerate(non_mod_tools):
        context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name=tool_name,
            tool_arguments={},
        )

        # Process the tool call
        can_handle_result = await handler.can_handle(context)

        # Should not be handled
        assert can_handle_result is False

        # Verify state remains clean (or still doesn't exist)
        state = handler._get_session_state(session_id)
        if state is not None:
            assert state.is_dirty is False, (
                f"Session should remain clean after non-modification tool {i + 1}. "
                f"Tool: '{tool_name}'"
            )
            assert state.modification_count == 0, (
                f"Modification count should remain 0 after non-modification tool {i + 1}. "
                f"Tool: '{tool_name}'"
            )


@given(
    test_command=execution_command_strategy(),
    non_mod_tool=non_modification_tool_strategy(),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_mixed_clean_operations_maintain_clean_state(
    test_command: str, non_mod_tool: str, session_id: str
) -> None:
    """
    Property 3: Mixed Clean Operations Maintain Clean State.

    For any session in clean state, if a mix of test executions and
    non-modification tools are processed, the state should remain clean.

    Validates: Requirements 2.16
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Process test execution
    context_test = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": test_command},
    )
    await handler.can_handle(context_test)

    # Verify clean after test
    state_after_test = handler._get_session_state(session_id)
    assert state_after_test is not None
    assert state_after_test.is_dirty is False

    # Process non-modification tool
    context_non_mod = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=non_mod_tool,
        tool_arguments={},
    )
    await handler.can_handle(context_non_mod)

    # Verify still clean after non-modification
    state_after_non_mod = handler._get_session_state(session_id)
    assert state_after_non_mod is not None
    assert state_after_non_mod.is_dirty is False, (
        f"Session should remain clean after mixed operations. "
        f"Test: '{test_command}', Tool: '{non_mod_tool}'"
    )
    assert state_after_non_mod.modification_count == 0


@given(
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_3_initial_state_is_clean(session_id: str) -> None:
    """
    Property 3: Initial State is Clean.

    For any new session, the initial state should be clean (no modifications).

    Validates: Requirements 1.5
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Get initial state (should be None, which means clean)
    state = handler._get_session_state(session_id)

    # Either no state exists (clean) or state is explicitly clean
    if state is not None:
        assert state.is_dirty is False, "Initial state should be clean"
        assert state.modification_count == 0, "Initial modification count should be 0"
