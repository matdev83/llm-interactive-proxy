"""Property-based tests for steering injection on dirty completion.

Feature: test-execution-reminder
Property 5: Steering Injection on Dirty Completion
Validates: Requirements 3.4, 4.1
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.test_execution_reminder.test_execution_reminder_handler import (
    DEFAULT_STEERING_MESSAGE,
    TestExecutionReminderHandler,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating test data
# ============================================================================


@st.composite
def file_modification_tool_strategy(draw: Any) -> str:
    """Generate file modification tool names."""
    base_tools = [
        "write_file",
        "replace_lines",
        "str_replace",
        "apply_diff",
        "patch_file",
        "multiedit",
        "fs/write_text_file",
    ]
    return draw(st.sampled_from(base_tools))


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
    file_tool=file_modification_tool_strategy(),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_5_steering_injection_on_dirty_completion(
    file_tool: str,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 5: Steering Injection on Dirty Completion.

    For any session in dirty state (after file modification), if a completion
    signal is detected, then:
    1. can_handle should return True
    2. handle should return should_swallow=True
    3. handle should return a steering message
    4. handle should include appropriate metadata

    Validates: Requirements 3.4, 4.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Step 1: Mark session as dirty with file modification
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool,
        tool_arguments={},
    )
    await handler.can_handle(file_context)

    # Verify session is dirty
    state = handler._get_session_state(session_id)
    assert state is not None, f"Session state should exist for session {session_id}"
    assert state.is_dirty is True, "Session should be dirty after file modification"

    # Step 2: Send completion signal
    tool_name, tool_arguments, response_text = completion_signal
    completion_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={"content": response_text},
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )

    # Step 3: Verify can_handle returns True for dirty completion
    can_handle_result = await handler.can_handle(completion_context)
    assert can_handle_result is True, (
        f"can_handle should return True for completion signal in dirty state. "
        f"Tool: {tool_name}, Response: {response_text}"
    )

    # Step 4: Verify handle returns steering message
    handle_result = await handler.handle(completion_context)

    assert (
        handle_result.should_swallow is True
    ), "handle should return should_swallow=True for dirty completion"

    assert (
        handle_result.replacement_response is not None
    ), "handle should return a replacement_response for dirty completion"

    assert (
        len(handle_result.replacement_response) > 0
    ), "Replacement response should not be empty"

    assert (
        handle_result.metadata is not None
    ), "handle should return metadata for dirty completion"

    assert "handler" in handle_result.metadata, "Metadata should include handler name"

    assert (
        handle_result.metadata["handler"] == "test_execution_reminder_handler"
    ), "Metadata handler should be 'test_execution_reminder_handler'"

    assert "source" in handle_result.metadata, "Metadata should include source"

    assert (
        handle_result.metadata["source"] == "test_execution_reminder"
    ), "Metadata source should be 'test_execution_reminder'"


@given(
    file_tool=file_modification_tool_strategy(),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_5_custom_steering_message(
    file_tool: str,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 5: Custom Steering Message.

    For any custom steering message configured, the handler should use
    that message instead of the default when injecting steering on dirty
    completion.

    Validates: Requirements 4.1, 4.4
    """
    # Create handler with custom message
    custom_message = "Custom test reminder: Please run tests before completing!"
    handler = TestExecutionReminderHandler(enabled=True, message=custom_message)

    # Mark session as dirty
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool,
        tool_arguments={},
    )
    await handler.can_handle(file_context)

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

    # Verify handle returns custom message
    handle_result = await handler.handle(completion_context)

    assert handle_result.should_swallow is True
    assert handle_result.replacement_response == custom_message, (
        f"Handler should use custom message. "
        f"Expected: {custom_message}, Got: {handle_result.replacement_response}"
    )


@given(
    file_tool=file_modification_tool_strategy(),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_5_default_steering_message(
    file_tool: str,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 5: Default Steering Message.

    When no custom message is configured, the handler should use the
    default steering message.

    Validates: Requirements 4.1, 4.4
    """
    # Create handler without custom message
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session as dirty
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool,
        tool_arguments={},
    )
    await handler.can_handle(file_context)

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

    # Verify handle returns default message
    handle_result = await handler.handle(completion_context)

    assert handle_result.should_swallow is True
    assert handle_result.replacement_response == DEFAULT_STEERING_MESSAGE, (
        f"Handler should use default message. "
        f"Expected: {DEFAULT_STEERING_MESSAGE}, "
        f"Got: {handle_result.replacement_response}"
    )


@given(
    modification_count=st.integers(min_value=1, max_value=10),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_5_multiple_modifications_before_completion(
    modification_count: int,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 5: Multiple Modifications Before Completion.

    For any number of file modifications before completion, the handler
    should still inject steering on completion signal.

    Validates: Requirements 3.4, 4.1
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Perform multiple modifications
    for _ in range(modification_count):
        file_context = ToolCallContext(
            session_id=session_id,
            backend_name="test_backend",
            model_name="test_model",
            full_response={},
            tool_name="write_file",
            tool_arguments={},
        )
        await handler.can_handle(file_context)

    # Verify session is dirty with correct count
    state = handler._get_session_state(session_id)
    assert state is not None
    assert state.is_dirty is True
    assert state.modification_count == modification_count

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

    # Verify steering is injected
    can_handle_result = await handler.can_handle(completion_context)
    assert can_handle_result is True

    handle_result = await handler.handle(completion_context)
    assert handle_result.should_swallow is True
    assert handle_result.replacement_response is not None

    # Verify metadata includes modification count
    assert handle_result.metadata is not None
    assert "modification_count" in handle_result.metadata
    assert handle_result.metadata["modification_count"] == modification_count


@given(
    file_tool=file_modification_tool_strategy(),
    completion_signal=completion_signal_strategy(),
    session_id=session_id_strategy(),
)
@property_test_settings()
async def test_property_5_metadata_includes_tool_name(
    file_tool: str,
    completion_signal: tuple[str, dict[str, Any], str],
    session_id: str,
) -> None:
    """
    Property 5: Metadata Includes Tool Name.

    The metadata returned by handle should include the tool name that
    triggered the completion signal.

    Validates: Requirements 4.5
    """
    # Create handler
    handler = TestExecutionReminderHandler(enabled=True)

    # Mark session as dirty
    file_context = ToolCallContext(
        session_id=session_id,
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name=file_tool,
        tool_arguments={},
    )
    await handler.can_handle(file_context)

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

    # Verify metadata includes tool name
    handle_result = await handler.handle(completion_context)

    assert handle_result.metadata is not None
    assert "tool_name" in handle_result.metadata
    assert handle_result.metadata["tool_name"] == tool_name, (
        f"Metadata should include the completion tool name. "
        f"Expected: {tool_name}, Got: {handle_result.metadata.get('tool_name')}"
    )
