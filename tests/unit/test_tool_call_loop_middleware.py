"""Unit tests for the tool call loop detection middleware."""

import json

import pytest
from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_call_loop_middleware import (
    ToolCallLoopDetectionMiddleware,
)
from src.tool_call_loop.config import ToolLoopMode


class ConcreteToolCallLoopDetectionMiddleware(ToolCallLoopDetectionMiddleware):
    async def process_response(self, response, context):
        return response

    async def process_streaming_chunk(self, chunk, context):
        return chunk


@pytest.fixture
def middleware() -> ToolCallLoopDetectionMiddleware:
    """Create a ToolCallLoopDetectionMiddleware instance."""
    return ConcreteToolCallLoopDetectionMiddleware()


@pytest.fixture
def loop_config() -> LoopDetectionConfiguration:
    """Create a LoopDetectionConfiguration instance."""
    return LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=3,
        tool_loop_ttl_seconds=60,
        tool_loop_mode=ToolLoopMode.BREAK,
    )


@pytest.fixture
def tool_call_response() -> ProcessedResponse:
    """Create a response with tool calls."""
    response_dict = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677858242,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "New York"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    return ProcessedResponse(content=response_dict)


@pytest.mark.asyncio
async def test_process_no_context(middleware: ToolCallLoopDetectionMiddleware) -> None:
    """Test that the middleware returns the response unchanged if no context is provided."""
    response = ProcessedResponse(content={})
    result = await middleware.process(response, "session123", context={})
    assert result == response


@pytest.mark.asyncio
async def test_process_no_config(middleware: ToolCallLoopDetectionMiddleware) -> None:
    """Test that the middleware returns the response unchanged if no config is provided."""
    response = ProcessedResponse(content={})
    result = await middleware.process(response, "session123", context={})
    assert result == response


@pytest.mark.asyncio
async def test_process_disabled(middleware: ToolCallLoopDetectionMiddleware) -> None:
    """Test that the middleware returns the response unchanged if disabled."""
    # Create a new config with tool loop detection disabled
    disabled_config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=False,
        tool_loop_max_repeats=3,
        tool_loop_ttl_seconds=60,
        tool_loop_mode=ToolLoopMode.BREAK,
    )
    response = ProcessedResponse(content={})
    result = await middleware.process(
        response, "session123", context={"config": disabled_config}
    )
    assert result == response


@pytest.mark.asyncio
async def test_process_no_tool_calls(
    middleware: ToolCallLoopDetectionMiddleware, loop_config: LoopDetectionConfiguration
) -> None:
    """Test that the middleware returns the response unchanged if no tool calls are present."""
    response = ProcessedResponse(content={})
    result = await middleware.process(
        response, "session123", context={"config": loop_config}
    )
    assert result == response


@pytest.mark.asyncio
async def test_process_with_tool_calls(
    middleware, loop_config, tool_call_response
) -> None:
    """Test that the middleware processes responses with tool calls."""
    # First call should pass through
    result = await middleware.process(
        tool_call_response, "session123", context={"config": loop_config}
    )
    assert result == tool_call_response

    # Second call should pass through
    result = await middleware.process(
        tool_call_response, "session123", context={"config": loop_config}
    )
    assert result == tool_call_response

    # Third call should raise an exception (max_repeats=3)
    with pytest.raises(ToolCallLoopError) as exc_info:
        await middleware.process(
            tool_call_response, "session123", context={"config": loop_config}
        )

    # Check the exception details
    assert "Tool call loop detected" in str(exc_info.value)
    assert exc_info.value.details["tool_name"] == "get_weather"
    assert exc_info.value.details["repetitions"] == 3


@pytest.mark.asyncio
async def test_process_tool_calls_from_bytes(
    middleware, loop_config, tool_call_response
) -> None:
    """Ensure tool call extraction works when the response content is bytes."""
    payload_bytes = json.dumps(tool_call_response.content).encode("utf-8")
    response = ProcessedResponse(content=payload_bytes)

    session_id = "session-bytes"

    # First two calls should pass through while populating the tracker
    for _ in range(loop_config.tool_loop_max_repeats - 1):
        result = await middleware.process(
            response, session_id, context={"config": loop_config}
        )
        assert result == response

    # The next identical call should trigger loop protection
    with pytest.raises(ToolCallLoopError) as exc_info:
        await middleware.process(response, session_id, context={"config": loop_config})

    assert "Tool call loop detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reset_session(middleware, loop_config, tool_call_response) -> None:
    """Test that resetting a session clears its tracking state."""
    # First call should pass through
    await middleware.process(
        tool_call_response, "session123", context={"config": loop_config}
    )

    # Reset the session
    middleware.reset_session("session123")

    # After reset, we should be able to make max_repeats calls again without error
    for _ in range(loop_config.tool_loop_max_repeats - 1):
        result = await middleware.process(
            tool_call_response, "session123", context={"config": loop_config}
        )
        assert result == tool_call_response


@pytest.mark.asyncio
async def test_config_changes_update_existing_tracker(
    middleware: ToolCallLoopDetectionMiddleware, tool_call_response: ProcessedResponse
) -> None:
    """Config updates should refresh thresholds for existing session trackers."""

    session_id = "session123"
    initial_config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=4,
        tool_loop_ttl_seconds=60,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Prime the tracker with the initial configuration
    await middleware.process(
        tool_call_response, session_id, context={"config": initial_config}
    )

    updated_config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=60,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # The stricter config should take effect immediately for the existing tracker
    with pytest.raises(ToolCallLoopError):
        await middleware.process(
            tool_call_response, session_id, context={"config": updated_config}
        )


@pytest.mark.asyncio
async def test_different_tool_calls(middleware, loop_config) -> None:
    """Test that different tool calls are tracked separately."""
    # Create two different tool call responses
    tool_call_1 = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "New York"}',
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )

    tool_call_2 = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "London"}',
                                }
                            }
                        ]
                    }
                }
            ]
        },
    )

    # Use the same tool call repeatedly to trigger the loop detection
    for _ in range(
        loop_config.tool_loop_max_repeats - 1
    ):  # One less than the threshold
        result = await middleware.process(
            tool_call_1, "session123", context={"config": loop_config}
        )
        assert result == tool_call_1

    # The next call with the same tool should trigger the loop detection
    with pytest.raises(ToolCallLoopError):
        await middleware.process(
            tool_call_1, "session123", context={"config": loop_config}
        )

    # Reset the session before testing the second tool call
    middleware.reset_session("session123")

    # Now we can test the second tool call
    for _ in range(
        loop_config.tool_loop_max_repeats - 1
    ):  # One less than the threshold
        result = await middleware.process(
            tool_call_2, "session123", context={"config": loop_config}
        )
        assert result == tool_call_2

    # The next call with the second tool should trigger the loop detection
    with pytest.raises(ToolCallLoopError):
        await middleware.process(
            tool_call_2, "session123", context={"config": loop_config}
        )
