"""Property-based tests for no steering on clean completion.

Feature: test-execution-reminder
Property 6: No Steering on Clean Completion
Validates: Requirements 3.3
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
# Strategies for generating test data
# ============================================================================


@st.composite
def completion_signal_strategy(draw: Any) -> tuple[str, dict[str, Any], str]:
    """Generate completion signals (tool_name, tool_arguments, response_text).

    Returns a tuple of (tool_name, tool_arguments, response_text) that
    represents a completion signal.
    """
    # Choose between tool-based or message-based completion
    use_tool = draw(st.booleans())

    if use_tool:
        # Use a completion tool name
        completion_tools = [
            "task_complete",
            "mark_complete",
            "finish_task",
            "complete",
            "done",
        ]
        tool_name = draw(st.sampled_from(completion_tools))
        tool_arguments = {}
        response_text = "Some response"
    else:
        # Use a completion message
        tool_name = "some_tool"
        tool_arguments = {}
        completion_messages = [
            "The task is complete",
            "Implementation is done",
            "All tests pass",
            "Ready for review",
            "Finished implementing",
            "Task complete",
            "Completed the task",
        ]
        response_text = draw(st.sampled_from(completion_messages))

    return tool_name, tool_arguments, response_text


@st.composite
def session_id_strategy(draw: Any) -> str:
    """Generate session IDs."""
    # Use printable ASCII characters to avoid encoding issues
    return draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(
                min_codepoint=32, max_codepoint=126, blacklist_categories=()
            ),
        )
    )


# ============================================================================
# Property Tests
# ============================================================================


@given(
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_no_steering_on_clean_completion_new_session(
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: No Steering on Clean Completion (New Session).

    For any new session (clean state by default), if a completion signal
    is detected, then:
    1. can_handle should return False
    2. handle should return should_swallow=False

    Validates: Requirements 3.3
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Send completion signal without any prior modifications
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Verify can_handle returns False for clean completion
    can_handle_result = await handler.can_handle(completion_context)
    assert can_handle_result is False, (
        f"can_handle should return False for completion signal in clean state. "
        f"Tool: {tool_name}, Response: {response_text}"
    )

    # Verify handle returns no swallow
    handle_result = await handler.handle(completion_context)
    assert (
        handle_result.should_swallow is False
    ), "handle should return should_swallow=False for clean completion"


@given(
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_no_steering_after_test_execution(
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: No Steering After Test Execution.

    For any session that was dirty but then had tests run (now clean),
    if a completion signal is detected, then:
    1. can_handle should return False
    2. handle should return should_swallow=False

    Validates: Requirements 3.3
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Step 1: Mark session as dirty
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="write_file",
        tool_arguments={},
    )
    await handler.can_handle(file_context)

    # Verify dirty
    state = handler._get_session_state(session_id)
    assert state is not None
    assert state.is_dirty is True

    # Step 2: Run tests to mark clean
    test_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest tests/"},
    )
    await handler.can_handle(test_context)

    # Verify clean
    state = handler._get_session_state(session_id)
    assert state is not None
    assert state.is_dirty is False

    # Step 3: Send completion signal
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Verify no steering is injected
    can_handle_result = await handler.can_handle(completion_context)
    assert (
        can_handle_result is False
    ), "can_handle should return False for completion signal after tests run"

    handle_result = await handler.handle(completion_context)
    assert (
        handle_result.should_swallow is False
    ), "handle should return should_swallow=False for clean completion"


@given(
    test_command=st.sampled_from(
        [
            "pytest",
            "python -m pytest",
            "jest",
            "npm test",
            "cargo test",
            "go test",
            "mvn test",
            "dotnet test",
        ]
    ),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_no_steering_after_any_test_runner(
    test_command: str,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: No Steering After Any Test Runner.

    For any test runner command across different languages, after running
    tests, completion signals should not trigger steering.

    Validates: Requirements 3.3
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session as dirty
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="write_file",
        tool_arguments={},
    )
    await handler.can_handle(file_context)

    # Run tests with the given test command
    test_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": test_command},
    )
    await handler.can_handle(test_context)

    # Verify clean
    state = handler._get_session_state(session_id)
    assert state is not None
    assert (
        state.is_dirty is False
    ), f"Session should be clean after running '{test_command}'"

    # Send completion signal
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Verify no steering
    can_handle_result = await handler.can_handle(completion_context)
    assert can_handle_result is False

    handle_result = await handler.handle(completion_context)
    assert handle_result.should_swallow is False


@given(
    test_runs=st.integers(min_value=1, max_value=5),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_no_steering_after_multiple_test_runs(
    test_runs: int,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: No Steering After Multiple Test Runs.

    For any number of test runs in succession (all in clean state),
    completion signals should not trigger steering.

    Validates: Requirements 3.3, 8.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session as dirty first
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="write_file",
        tool_arguments={},
    )
    await handler.can_handle(file_context)

    # Run tests multiple times
    for _ in range(test_runs):
        test_context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest tests/"},
        )
        await handler.can_handle(test_context)

        # Verify still clean after each test run
        state = handler._get_session_state(session_id)
        assert state is not None
        assert state.is_dirty is False

    # Send completion signal
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Verify no steering
    can_handle_result = await handler.can_handle(completion_context)
    assert can_handle_result is False

    handle_result = await handler.handle(completion_context)
    assert handle_result.should_swallow is False


@given(
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_clean_state_preserved_through_completion(
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: Clean State Preserved Through Completion.

    When a completion signal is processed in clean state, the state
    should remain clean (not transition to dirty).

    Validates: Requirements 3.3
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Send completion signal in clean state
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Process completion
    await handler.can_handle(completion_context)
    await handler.handle(completion_context)

    # Verify state is still clean (or doesn't exist, which is also clean)
    state = handler._get_session_state(session_id)
    if state is not None:
        assert (
            state.is_dirty is False
        ), "State should remain clean after processing completion signal"


@given(
    completion_signals=st.lists(
        completion_signal_strategy(),
        min_size=1,
        max_size=5,
    ),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_multiple_completions_in_clean_state(
    completion_signals: list[tuple[str, dict[str, Any], str]],
    session_id: str,
) -> None:
    """
    Property 6: Multiple Completions in Clean State.

    For any number of completion signals in clean state, none should
    trigger steering.

    Validates: Requirements 3.3
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Process multiple completion signals
    for tool_name, tool_arguments, response_text in completion_signals:
        completion_context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={"content": response_text},
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

        # Verify no steering for each completion
        can_handle_result = await handler.can_handle(completion_context)
        assert can_handle_result is False, (
            f"can_handle should return False for completion in clean state. "
            f"Tool: {tool_name}"
        )

        handle_result = await handler.handle(completion_context)
        assert handle_result.should_swallow is False, (
            f"handle should return should_swallow=False for clean completion. "
            f"Tool: {tool_name}"
        )


@given(
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_6_disabled_handler_no_steering(
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 6: Disabled Handler No Steering.

    When the handler is disabled, completion signals should never trigger
    steering, regardless of state.

    Validates: Requirements 3.3, 5.11
    """
    # Create disabled handler
    handler = TestExecutionReminderHandler(enabled=False)

    # Mark session as dirty (even though handler is disabled)
    handler._mark_session_dirty(session_id)

    # Send completion signal
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Verify no steering (handler is disabled)
    can_handle_result = await handler.can_handle(completion_context)
    assert (
        can_handle_result is False
    ), "Disabled handler should return False from can_handle"

    handle_result = await handler.handle(completion_context)
    assert (
        handle_result.should_swallow is False
    ), "Disabled handler should return should_swallow=False"
