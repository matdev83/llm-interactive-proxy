"""Property-based tests for disabled feature behavior.

**Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
**Validates: Requirements 5.11**
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


# Strategy for generating various tool names (file modifications, test runners, completion signals)
@st.composite
def any_tool_name(draw: Any) -> str:
    """Generate any type of tool name."""
    tool_type = draw(
        st.sampled_from(
            [
                "file_modification",
                "test_runner",
                "completion_signal",
                "unknown",
            ]
        )
    )

    if tool_type == "file_modification":
        return draw(
            st.sampled_from(
                [
                    "write_file",
                    "str_replace",
                    "apply_diff",
                    "patch_file",
                    "multiedit",
                    "fs/write_text_file",
                ]
            )
        )
    elif tool_type == "test_runner":
        return draw(
            st.sampled_from(
                [
                    "bash",
                    "exec",
                    "execute_command",
                    "shell",
                ]
            )
        )
    elif tool_type == "completion_signal":
        return draw(
            st.sampled_from(
                [
                    "task_complete",
                    "mark_complete",
                    "finish_task",
                    "complete",
                ]
            )
        )
    else:  # unknown
        return draw(st.text(min_size=1, max_size=20))


# Strategy for generating tool arguments
@st.composite
def any_tool_arguments(draw: Any) -> dict[str, Any]:
    """Generate various tool arguments."""
    arg_type = draw(
        st.sampled_from(
            [
                "empty",
                "file_args",
                "command_args",
                "completion_args",
            ]
        )
    )

    if arg_type == "empty":
        return {}
    elif arg_type == "file_args":
        return {
            "path": draw(st.text(min_size=1, max_size=50)),
            "content": draw(st.text(min_size=0, max_size=100)),
        }
    elif arg_type == "command_args":
        return {
            "command": draw(
                st.sampled_from(
                    [
                        "pytest",
                        "npm test",
                        "cargo test",
                        "go test",
                        "python -m pytest",
                    ]
                )
            ),
        }
    else:  # completion_args
        return {
            "message": draw(st.text(min_size=1, max_size=100)),
        }


@pytest.mark.asyncio
@settings(max_examples=50, deadline=None)
@given(
    tool_name=any_tool_name(),
    tool_arguments=any_tool_arguments(),
    session_id=st.text(min_size=1, max_size=50),
)
async def test_disabled_feature_does_not_track_state(
    tool_name: str,
    tool_arguments: dict[str, Any],
    session_id: str,
) -> None:
    """Property: When disabled, no state tracking should occur for any tool call.

    This property verifies that when the feature is disabled, the handler does
    not track any session state, regardless of the tool type (file modification,
    test execution, or completion signal).

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED
    handler = TestExecutionReminderHandler(enabled=False)

    # Create a context with the generated tool
    context = ToolCallContext(
        session_id=session_id,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Process the tool call
    can_handle_result = await handler.can_handle(context)

    # Assert: Handler should not handle any tool when disabled
    assert (
        not can_handle_result
    ), f"Disabled handler incorrectly claimed to handle tool '{tool_name}'"

    # Assert: No session state should be created or modified
    assert (
        session_id not in handler._session_state
    ), f"Disabled handler incorrectly created session state for '{session_id}'"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=None)
@given(
    session_id=st.text(min_size=1, max_size=50),
)
async def test_disabled_feature_does_not_inject_steering(
    session_id: str,
) -> None:
    """Property: When disabled, no steering messages should be injected.

    This property verifies that even if a completion signal is detected in what
    would be a dirty state, the disabled handler does not inject steering messages.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED
    handler = TestExecutionReminderHandler(enabled=False)

    # Simulate a scenario that would trigger steering if enabled:
    # 1. File modification
    file_mod_context = ToolCallContext(
        session_id=session_id,
        tool_name="write_file",
        tool_arguments={"path": "test.py", "content": "test"},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # 2. Completion signal
    completion_context = ToolCallContext(
        session_id=session_id,
        tool_name="task_complete",
        tool_arguments={},
        full_response={"content": "Task is complete and ready for review"},
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Process both tool calls
    can_handle_file = await handler.can_handle(file_mod_context)
    can_handle_completion = await handler.can_handle(completion_context)

    # Assert: Handler should not handle either tool when disabled
    assert not can_handle_file, "Disabled handler incorrectly handled file modification"
    assert (
        not can_handle_completion
    ), "Disabled handler incorrectly handled completion signal"

    # Assert: No session state should exist
    assert (
        session_id not in handler._session_state
    ), "Disabled handler incorrectly created session state"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=None)
@given(
    session_id=st.text(min_size=1, max_size=50),
)
async def test_disabled_feature_allows_all_requests_through(
    session_id: str,
) -> None:
    """Property: When disabled, all requests should be allowed through.

    This property verifies that the disabled handler always returns False from
    can_handle, ensuring all requests pass through without intervention.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED
    handler = TestExecutionReminderHandler(enabled=False)

    # Create a sequence of tool calls that would normally trigger various behaviors
    tool_calls = [
        # File modifications
        ("write_file", {"path": "test1.py", "content": "test"}),
        ("str_replace", {"path": "test2.py", "old": "old", "new": "new"}),
        ("apply_diff", {"path": "test3.py", "diff": "diff"}),
        # Test executions
        ("bash", {"command": "pytest"}),
        ("exec", {"command": "npm test"}),
        # Completion signals
        ("task_complete", {}),
        ("complete", {"message": "Done"}),
    ]

    # Act & Assert: All tool calls should be allowed through
    for tool_name, tool_arguments in tool_calls:
        context = ToolCallContext(
            session_id=session_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            full_response=None,
            backend_name="test-backend",
            model_name="test-model",
        )

        can_handle_result = await handler.can_handle(context)

        assert (
            not can_handle_result
        ), f"Disabled handler incorrectly handled tool '{tool_name}'"

    # Assert: No session state should exist after all these calls
    assert (
        session_id not in handler._session_state
    ), "Disabled handler incorrectly created session state"


@pytest.mark.asyncio
async def test_disabled_feature_handle_returns_no_swallow() -> None:
    """Test that handle() returns should_swallow=False when disabled.

    This test verifies that even if handle() is called on a disabled handler
    (which shouldn't happen in practice), it returns a result that allows
    the request through.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED
    handler = TestExecutionReminderHandler(enabled=False)

    # Create a context that would trigger steering if enabled
    context = ToolCallContext(
        session_id="test-session",
        tool_name="task_complete",
        tool_arguments={},
        full_response={"content": "Task is complete"},
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Call handle directly (bypassing can_handle)
    result = await handler.handle(context)

    # Assert: Result should not swallow the request
    assert (
        not result.should_swallow
    ), "Disabled handler incorrectly swallowed request in handle()"
    assert (
        result.replacement_response is None
    ), "Disabled handler incorrectly provided replacement response"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=None)
@given(
    custom_message=st.text(min_size=1, max_size=200),
    session_id=st.text(min_size=1, max_size=50),
)
async def test_disabled_feature_ignores_custom_message(
    custom_message: str,
    session_id: str,
) -> None:
    """Property: When disabled, custom steering messages should be ignored.

    This property verifies that even if a custom steering message is configured,
    it is never used when the feature is disabled.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED but custom message
    handler = TestExecutionReminderHandler(
        enabled=False,
        message=custom_message,
    )

    # Create a context that would trigger steering if enabled
    context = ToolCallContext(
        session_id=session_id,
        tool_name="task_complete",
        tool_arguments={},
        full_response={"content": "Task is complete"},
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Process the completion signal
    can_handle_result = await handler.can_handle(context)

    # Assert: Handler should not handle the request
    assert (
        not can_handle_result
    ), "Disabled handler incorrectly handled completion signal"

    # If we call handle anyway, it should not use the custom message
    result = await handler.handle(context)
    assert not result.should_swallow, "Disabled handler incorrectly swallowed request"
    assert (
        result.replacement_response is None
    ), "Disabled handler incorrectly used custom message"


@pytest.mark.asyncio
async def test_disabled_feature_logs_initialization() -> None:
    """Test that disabled feature logs initialization message.

    This test verifies that when the handler is initialized with enabled=False,
    it logs an appropriate initialization message indicating disabled status.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    from unittest.mock import patch

    # Arrange: Mock the logger
    with patch(
        "src.services.test_execution_reminder.test_execution_reminder_handler.logger"
    ) as mock_logger:
        # Act: Create handler with feature DISABLED
        TestExecutionReminderHandler(enabled=False)

        # Assert: Logger should have been called with disabled message
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert (
            "disabled" in call_args[0].lower()
        ), "Disabled handler did not log appropriate initialization message"


@pytest.mark.asyncio
@settings(max_examples=50, deadline=None)
@given(
    state_ttl_seconds=st.integers(min_value=1, max_value=3600),
    max_sessions=st.integers(min_value=1, max_value=10000),
)
async def test_disabled_feature_ignores_configuration(
    state_ttl_seconds: int,
    max_sessions: int,
) -> None:
    """Property: When disabled, configuration parameters should have no effect.

    This property verifies that configuration parameters like TTL and max sessions
    are effectively ignored when the feature is disabled, since no state tracking
    occurs.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    # Arrange: Create handler with feature DISABLED and various config
    handler = TestExecutionReminderHandler(
        enabled=False,
        state_ttl_seconds=state_ttl_seconds,
        max_sessions=max_sessions,
    )

    # Create multiple contexts to test that config is ignored
    contexts = [
        ToolCallContext(
            session_id=f"session-{i}",
            tool_name="write_file",
            tool_arguments={"path": f"test{i}.py", "content": "test"},
            full_response=None,
            backend_name="test-backend",
            model_name="test-model",
        )
        for i in range(10)
    ]

    # Act: Process all contexts
    for context in contexts:
        can_handle_result = await handler.can_handle(context)
        assert not can_handle_result

    # Assert: No session state should exist, regardless of config
    assert (
        len(handler._session_state) == 0
    ), "Disabled handler incorrectly created session state despite being disabled"


@pytest.mark.asyncio
async def test_disabled_feature_has_zero_performance_impact() -> None:
    """Test that disabled feature has minimal performance impact.

    This test verifies that when disabled, the handler returns immediately
    from can_handle without performing any expensive operations.

    **Feature: test-execution-reminder, Property 12: Disabled Feature Has No Effect**
    **Validates: Requirements 5.11**
    """
    import time

    # Arrange: Create handler with feature DISABLED
    handler = TestExecutionReminderHandler(enabled=False)

    # Create a context
    context = ToolCallContext(
        session_id="test-session",
        tool_name="write_file",
        tool_arguments={"path": "test.py", "content": "test"},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Measure time for can_handle
    start_time = time.perf_counter()
    for _ in range(1000):
        await handler.can_handle(context)
    end_time = time.perf_counter()

    # Assert: Should be very fast (less than 10ms for 1000 calls)
    elapsed_ms = (end_time - start_time) * 1000
    assert elapsed_ms < 10, (
        f"Disabled handler took {elapsed_ms:.2f}ms for 1000 calls, "
        "indicating it's not returning early"
    )
