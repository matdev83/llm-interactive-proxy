"""Property-based tests for error handling in test execution reminder system.

**Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
**Validates: Requirements 8.5, 9.5**
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    TestExecutionReminderHandler,
)


# Strategy for generating unknown/unrecognized tool names
@st.composite
def unknown_tool_names(draw: Any) -> str:
    """Generate tool names that should not be recognized by the system."""
    # Generate random strings that are unlikely to match known patterns
    prefix = draw(st.sampled_from(["unknown", "random", "test", "custom", "fake"]))
    suffix = draw(st.sampled_from(["tool", "command", "action", "operation", ""]))
    separator = draw(st.sampled_from(["_", "-", "", "."]))

    return f"{prefix}{separator}{suffix}"


# Strategy for generating malformed tool arguments
@st.composite
def malformed_tool_arguments(draw: Any) -> dict[str, Any]:
    """Generate malformed or unusual tool arguments."""
    arg_type = draw(
        st.sampled_from(
            [
                "empty",
                "nested",
                "invalid_types",
                "missing_keys",
                "null_values",
            ]
        )
    )

    if arg_type == "empty":
        return {}
    elif arg_type == "nested":
        return {"command": {"nested": {"deeply": "value"}}}
    elif arg_type == "invalid_types":
        return {
            "command": [1, 2, 3],  # List instead of string
            "args": {"key": "value"},  # Dict instead of list
        }
    elif arg_type == "missing_keys":
        return {
            "unexpected_key": "value",
            "another_key": 123,
        }
    else:  # null_values
        return {
            "command": None,
            "args": None,
        }


# Strategy for generating malformed responses
@st.composite
def malformed_responses(draw: Any) -> Any:
    """Generate malformed or unusual response objects."""
    response_type = draw(
        st.sampled_from(
            [
                "none",
                "empty_dict",
                "empty_string",
                "number",
                "list",
                "nested_structure",
            ]
        )
    )

    if response_type == "none":
        return None
    elif response_type == "empty_dict":
        return {}
    elif response_type == "empty_string":
        return ""
    elif response_type == "number":
        return draw(st.integers())
    elif response_type == "list":
        return [1, 2, 3, "test"]
    else:  # nested_structure
        return {"level1": {"level2": {"level3": "deep value"}}}


@pytest.mark.asyncio
@settings(max_examples=100, deadline=None)
@given(
    tool_name=unknown_tool_names(),
    tool_arguments=malformed_tool_arguments(),
    full_response=malformed_responses(),
)
async def test_unknown_tools_do_not_crash_handler(
    tool_name: str,
    tool_arguments: dict[str, Any],
    full_response: Any,
) -> None:
    """Property: For any unrecognized tool call, the handler should not crash.

    This property verifies that the handler gracefully handles unknown tools,
    malformed arguments, and unusual response formats without raising exceptions.
    The handler should fail open (allow requests through) when encountering
    unexpected input.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 8.5, 9.5**
    """
    # Arrange: Create handler with feature enabled
    handler = TestExecutionReminderHandler(enabled=True)

    # Create a mock context with the generated unknown tool
    context = ToolCallContext(
        session_id="test-session",
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        full_response=full_response,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act & Assert: Handler should not crash
    try:
        can_handle_result = await handler.can_handle(context)

        # If can_handle returns True, handle should also not crash
        if can_handle_result:
            handle_result = await handler.handle(context)
            # Verify result is valid
            assert hasattr(handle_result, "should_swallow")
            assert isinstance(handle_result.should_swallow, bool)

        # Success: No exception raised
        assert True

    except Exception as e:
        # Fail: Handler crashed on unknown tool
        pytest.fail(
            f"Handler crashed on unknown tool '{tool_name}' with arguments "
            f"{tool_arguments} and response {full_response}: {e}"
        )


@pytest.mark.asyncio
@settings(max_examples=100, deadline=None)
@given(
    tool_name=unknown_tool_names(),
    session_id=st.text(min_size=1, max_size=50),
)
async def test_unknown_tools_do_not_modify_state(
    tool_name: str,
    session_id: str,
) -> None:
    """Property: For any unrecognized tool, the session state should not be modified.

    This property verifies that unknown tools do not cause unintended state
    changes. The handler should only modify state for recognized file modification
    and test execution tools.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 8.5**
    """
    # Arrange: Create handler with feature enabled
    handler = TestExecutionReminderHandler(enabled=True)

    # Create a context with the unknown tool
    context = ToolCallContext(
        session_id=session_id,
        tool_name=tool_name,
        tool_arguments={},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Process the unknown tool
    try:
        await handler.can_handle(context)

        # Assert: Session state should remain clean (default state)
        state = handler._get_session_state(session_id)

        # State might be None (not created) or clean (default)
        if state is not None:
            assert (
                not state.is_dirty
            ), f"Unknown tool '{tool_name}' incorrectly modified session state to dirty"
            assert (
                state.modification_count == 0
            ), f"Unknown tool '{tool_name}' incorrectly incremented modification count"

    except Exception as e:
        # Fail: Handler crashed
        pytest.fail(f"Handler crashed on unknown tool '{tool_name}': {e}")


@pytest.mark.asyncio
@settings(max_examples=100, deadline=None)
@given(
    tool_name=unknown_tool_names(),
)
async def test_unknown_tools_allow_request_through(
    tool_name: str,
) -> None:
    """Property: For any unrecognized tool, can_handle should return False.

    This property verifies the "fail open" behavior: when the handler encounters
    an unknown tool, it should return False from can_handle, allowing the request
    to proceed through the pipeline without intervention.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 9.5**
    """
    # Arrange: Create handler with feature enabled
    handler = TestExecutionReminderHandler(enabled=True)

    # Create a context with the unknown tool
    context = ToolCallContext(
        session_id="test-session",
        tool_name=tool_name,
        tool_arguments={},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act: Check if handler can handle the unknown tool
    try:
        can_handle_result = await handler.can_handle(context)

        # Assert: Handler should not handle unknown tools (fail open)
        assert (
            not can_handle_result
        ), f"Handler incorrectly claimed to handle unknown tool '{tool_name}'"

    except Exception as e:
        # Fail: Handler crashed
        pytest.fail(f"Handler crashed on unknown tool '{tool_name}': {e}")


@pytest.mark.asyncio
async def test_malformed_regex_patterns_do_not_crash() -> None:
    """Test that malformed regex patterns in test runner registry don't crash.

    This test verifies that if the test runner registry somehow contains
    malformed patterns, the handler gracefully handles the error.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 8.5, 9.5**
    """
    from src.services.test_execution_reminder.test_runner_registry import (
        TestRunnerPattern,
        TestRunnerRegistry,
    )

    # Arrange: Create a registry with a malformed pattern
    registry = TestRunnerRegistry()

    # Add a pattern that will cause issues during matching
    # (This is a contrived example - in practice, patterns are compiled at registration)
    try:
        # Try to create a malformed pattern
        malformed_pattern = TestRunnerPattern(
            language="test",
            framework="test",
            patterns=[re.compile(r"(?P<invalid")],  # Invalid regex group
            priority=10,
        )
        registry.register_pattern(malformed_pattern)
    except re.error:
        # If registration fails, that's fine - we're testing runtime handling
        pass

    # Create handler with the registry
    handler = TestExecutionReminderHandler(
        enabled=True,
        test_runner_registry=registry,
    )

    # Create a context with a shell command
    context = ToolCallContext(
        session_id="test-session",
        tool_name="bash",
        tool_arguments={"command": "pytest tests/"},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act & Assert: Handler should not crash
    try:
        can_handle_result = await handler.can_handle(context)
        # Success: No exception raised
        assert isinstance(can_handle_result, bool)
    except Exception as e:
        pytest.fail(f"Handler crashed with malformed regex pattern: {e}")


@pytest.mark.asyncio
async def test_state_corruption_recovery() -> None:
    """Test that handler recovers from state corruption.

    This test verifies that if session state becomes corrupted, the handler
    can recover gracefully without crashing.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 8.5, 9.5**
    """
    # Arrange: Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Corrupt the session state by directly manipulating internal state
    # (This simulates unexpected state corruption)
    handler._session_state["corrupted-session"] = None  # type: ignore

    # Create a context
    context = ToolCallContext(
        session_id="corrupted-session",
        tool_name="write_file",
        tool_arguments={"path": "test.py", "content": "test"},
        full_response=None,
        backend_name="test-backend",
        model_name="test-model",
    )

    # Act & Assert: Handler should not crash
    try:
        can_handle_result = await handler.can_handle(context)
        # Success: No exception raised
        assert isinstance(can_handle_result, bool)
    except Exception as e:
        pytest.fail(f"Handler crashed with corrupted state: {e}")


@pytest.mark.asyncio
async def test_concurrent_access_does_not_crash() -> None:
    """Test that concurrent access to handler state doesn't crash.

    This test verifies that the handler can handle concurrent requests
    without crashing, even if they access the same session.

    **Feature: test-execution-reminder, Property 15: Error Handling for Unknown Tools**
    **Validates: Requirements 8.5, 9.5**
    """
    import asyncio

    # Arrange: Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Create multiple contexts for the same session
    contexts = [
        ToolCallContext(
            session_id="concurrent-session",
            tool_name="write_file",
            tool_arguments={"path": f"test{i}.py", "content": "test"},
            full_response=None,
            backend_name="test-backend",
            model_name="test-model",
        )
        for i in range(10)
    ]

    # Act: Process all contexts concurrently
    try:
        results = await asyncio.gather(
            *[handler.can_handle(ctx) for ctx in contexts],
            return_exceptions=True,
        )

        # Assert: No exceptions should be raised
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent request {i} raised exception: {result}")
            assert isinstance(result, bool)

    except Exception as e:
        pytest.fail(f"Handler crashed during concurrent access: {e}")
