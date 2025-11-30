"""Property-based tests for multiple test runs maintaining clean state.

Feature: test-execution-reminder
Property 13: Multiple Test Runs Maintain Clean State
Validates: Requirements 8.1
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
# Strategies for generating test commands
# ============================================================================


@st.composite
def execution_command_strategy(draw: Any) -> str:
    """Generate test execution commands across all supported languages."""
    commands = [
        # Python
        "pytest",
        "python -m pytest",
        "py.test",
        "python -m unittest",
        # JavaScript/TypeScript
        "jest",
        "npm test",
        "npm run test",
        "yarn test",
        "vitest",
        "mocha",
        "ava",
        # Rust
        "cargo test",
        # Go
        "go test",
        # Java
        "mvn test",
        "gradle test",
        "./gradlew test",
        # C#
        "dotnet test",
        # Ruby
        "rspec",
        "rake test",
        # PHP
        "phpunit",
        "composer test",
        # C/C++
        "ctest",
        "make test",
        # Swift
        "swift test",
        # Scala
        "sbt test",
        # Elixir
        "mix test",
        # Dart/Flutter
        "flutter test",
        "dart test",
    ]

    return draw(st.sampled_from(commands))


# ============================================================================
# Property Tests for Multiple Test Runs
# ============================================================================


@given(
    test_commands=st.lists(execution_command_strategy(), min_size=2, max_size=10),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_13_multiple_test_runs_maintain_clean_state(
    test_commands: list[str], session_id: str
) -> None:
    """
    Property 13: Multiple Test Runs Maintain Clean State.

    For any session in clean state, if multiple test execution commands are
    processed in succession, the state should remain clean without errors.

    This property ensures that running tests multiple times does not cause
    any state corruption or errors, and the session remains in a clean state
    throughout all test executions.

    Validates: Requirements 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Verify initial state is clean (no state exists yet)
    initial_state = handler._get_session_state(session_id)
    assert (
        initial_state is None or initial_state.is_dirty is False
    ), "Initial state should be clean"

    # Process each test command in succession
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

        # Test execution should not be handled (returns False)
        assert can_handle_result is False, (
            f"Test execution {i + 1} should not be handled. "
            f"Command: '{test_command}'"
        )

        # Verify state remains clean after each test
        state = handler._get_session_state(session_id)
        assert state is not None, (
            f"State should exist after test execution {i + 1}. "
            f"Command: '{test_command}'"
        )
        assert state.is_dirty is False, (
            f"Session should remain clean after test execution {i + 1}. "
            f"Command: '{test_command}'. "
            f"Multiple test runs should maintain clean state without errors."
        )
        assert state.modification_count == 0, (
            f"Modification count should remain 0 after test execution {i + 1}. "
            f"Command: '{test_command}'"
        )

    # Final verification: state should still be clean
    final_state = handler._get_session_state(session_id)
    assert final_state is not None, "Final state should exist"
    assert final_state.is_dirty is False, (
        f"Session should be clean after all {len(test_commands)} test executions. "
        f"Multiple test runs should maintain clean state without errors."
    )
    assert final_state.modification_count == 0, "Final modification count should be 0"


@given(
    test_count=st.integers(min_value=2, max_value=20),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_13_many_identical_test_runs_maintain_clean_state(
    test_count: int, session_id: str
) -> None:
    """
    Property 13: Many Identical Test Runs Maintain Clean State.

    For any session in clean state, if the same test command is executed
    multiple times in succession, the state should remain clean without errors.

    This tests the edge case where the exact same test is run repeatedly,
    ensuring no accumulation of state or errors occurs.

    Validates: Requirements 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Use a single test command
    test_command = "pytest"

    # Run the same test multiple times
    for i in range(test_count):
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
        state = handler._get_session_state(session_id)
        assert state is not None
        assert (
            state.is_dirty is False
        ), f"State should remain clean after identical test run {i + 1}/{test_count}"
        assert state.modification_count == 0


@given(
    test_commands=st.lists(execution_command_strategy(), min_size=2, max_size=10),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_13_test_runs_with_different_languages_maintain_clean_state(
    test_commands: list[str], session_id: str
) -> None:
    """
    Property 13: Test Runs with Different Languages Maintain Clean State.

    For any session in clean state, if test commands from different languages
    are executed in succession, the state should remain clean without errors.

    This ensures that switching between different test frameworks and languages
    does not cause any state issues.

    Validates: Requirements 8.1
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
        await handler.can_handle(context)

        # Verify state remains clean
        state = handler._get_session_state(session_id)
        assert state is not None
        assert (
            state.is_dirty is False
        ), f"State should remain clean after test {i + 1} with command '{test_command}'"
        assert state.modification_count == 0


@given(
    test_commands=st.lists(execution_command_strategy(), min_size=2, max_size=5),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_13_no_errors_during_multiple_test_runs(
    test_commands: list[str], session_id: str
) -> None:
    """
    Property 13: No Errors During Multiple Test Runs.

    For any session, running multiple test commands in succession should
    not raise any exceptions or errors.

    This explicitly tests the "without errors" part of Requirement 8.1.

    Validates: Requirements 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # This test should complete without raising any exceptions
    try:
        for test_command in test_commands:
            context = ToolCallContext(
                session_id=session_id,
                backend_name="test_backend",
                model_name="test_model",
                full_response={},
                tool_name="bash",
                tool_arguments={"command": test_command},
            )

            # Process the test execution - should not raise
            await handler.can_handle(context)

            # Verify state exists and is clean
            state = handler._get_session_state(session_id)
            assert state is not None
            assert state.is_dirty is False

    except Exception as e:
        # If any exception occurs, the test fails
        raise AssertionError(
            f"Multiple test runs should not raise errors. "
            f"Got exception: {type(e).__name__}: {e}"
        ) from e


@given(
    test_commands=st.lists(execution_command_strategy(), min_size=2, max_size=10),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings()
async def test_property_13_test_timestamps_update_correctly(
    test_commands: list[str], session_id: str
) -> None:
    """
    Property 13: Test Timestamps Update Correctly During Multiple Runs.

    For any session, when multiple tests are run in succession, the
    last_test_time timestamp should be updated after each test execution.

    This ensures that the state tracking is working correctly even with
    multiple test runs.

    Validates: Requirements 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    previous_test_time = 0.0

    # Process each test command
    for test_command in test_commands:
        context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": test_command},
        )

        # Process the test execution
        await handler.can_handle(context)

        # Verify timestamp was updated
        state = handler._get_session_state(session_id)
        assert state is not None
        assert state.last_test_time >= previous_test_time, (
            f"Test timestamp should be updated or remain the same. "
            f"Previous: {previous_test_time}, Current: {state.last_test_time}"
        )

        previous_test_time = state.last_test_time
