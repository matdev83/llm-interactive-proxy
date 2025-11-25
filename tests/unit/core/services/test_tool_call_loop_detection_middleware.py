from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.stream_context_registry import ToolCallBufferState
from src.core.services.tool_call_loop_middleware import ToolCallLoopDetectionMiddleware
from src.tool_call_loop.config import ToolLoopMode


def _make_response(tool_name: str, arguments: str = "{}") -> ProcessedResponse:
    return ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tool_name,
                                    "arguments": arguments,
                                }
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )


@pytest.mark.asyncio
async def test_tool_call_loop_detection_isolates_sessions() -> None:
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=4,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    async def run_session(session_id: str, tool_name: str) -> None:
        response = _make_response(tool_name)
        await middleware.process(
            response=response,
            session_id=session_id,
            context={"config": config},
            is_streaming=False,
        )

    await asyncio.gather(
        run_session("session-alpha", "alpha_tool"),
        run_session("session-beta", "beta_tool"),
    )

    assert set(middleware._session_trackers.keys()) == {"session-alpha", "session-beta"}

    alpha_tracker = middleware._session_trackers["session-alpha"]
    beta_tracker = middleware._session_trackers["session-beta"]

    assert [sig.tool_name for sig in alpha_tracker.signatures] == ["alpha_tool"]
    assert [sig.tool_name for sig in beta_tracker.signatures] == ["beta_tool"]

    # Subsequent calls for each session should reuse their own tracker
    await asyncio.gather(
        run_session("session-alpha", "alpha_tool"),
        run_session("session-beta", "beta_tool"),
    )

    assert len(alpha_tracker.signatures) == 2
    assert len(beta_tracker.signatures) == 2


@pytest.mark.asyncio
async def test_skips_processed_tool_calls() -> None:
    """Test that tool calls marked as processed are skipped."""
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Create a response with a processed tool call
    response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test_tool",
                                    "arguments": "{}",
                                },
                                "_already_processed": True,  # Mark as processed
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )

    # Process the response - should skip tracking
    result = await middleware.process(
        response=response,
        session_id="test-session",
        context={"config": config},
        is_streaming=False,
    )

    assert result == response
    # Tracker should not have any signatures since tool call was skipped
    tracker = middleware._session_trackers.get("test-session")
    assert tracker is None or len(tracker.signatures) == 0


@pytest.mark.asyncio
async def test_tracks_only_new_tool_calls() -> None:
    """Test that only new (unprocessed) tool calls are tracked."""
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Create a response with both processed and new tool calls
    response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "old_tool",
                                    "arguments": "{}",
                                },
                                "_already_processed": True,  # Processed
                            },
                            {
                                "function": {
                                    "name": "new_tool",
                                    "arguments": "{}",
                                },
                                # Not marked as processed
                            },
                        ]
                    }
                }
            ]
        },
        metadata={},
    )

    # Process the response
    result = await middleware.process(
        response=response,
        session_id="test-session",
        context={"config": config},
        is_streaming=False,
    )

    assert result == response
    # Tracker should only have the new tool call
    tracker = middleware._session_trackers["test-session"]
    assert len(tracker.signatures) == 1
    assert tracker.signatures[0].tool_name == "new_tool"


@pytest.mark.asyncio
async def test_marks_tool_calls_as_processed_after_tracking() -> None:
    """Test that tool calls are marked as processed after tracking."""
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Create a response with a new tool call
    tool_call = {
        "function": {
            "name": "test_tool",
            "arguments": "{}",
        },
    }
    response = ProcessedResponse(
        content={"choices": [{"message": {"tool_calls": [tool_call]}}]},
        metadata={},
    )

    # Process the response
    await middleware.process(
        response=response,
        session_id="test-session",
        context={"config": config},
        is_streaming=False,
    )

    # Tool call should now be marked as processed
    assert tool_call.get("_already_processed") is True
    # Message should also be marked as processed
    message_payload = cast(dict[str, Any], response.content)
    message = cast(dict[str, Any], message_payload["choices"][0]["message"])
    assert message.get("_tool_calls_processed") is True


@pytest.mark.asyncio
async def test_skips_processed_message() -> None:
    """Test that messages marked as processed are skipped entirely."""
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Create a response with a processed message
    response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test_tool",
                                    "arguments": "{}",
                                }
                            }
                        ],
                        "_tool_calls_processed": True,  # Mark message as processed
                    }
                }
            ]
        },
        metadata={},
    )

    # Process the response - should skip tracking
    result = await middleware.process(
        response=response,
        session_id="test-session",
        context={"config": config},
        is_streaming=False,
    )

    assert result == response
    # Tracker should not have any signatures since message was skipped
    tracker = middleware._session_trackers.get("test-session")
    assert tracker is None or len(tracker.signatures) == 0


@pytest.mark.asyncio
async def test_no_false_positives_from_historical_data() -> None:
    """Test that historical tool calls don't cause false loop detection."""
    from src.core.common.exceptions import ToolCallLoopError

    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,  # Low threshold
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Simulate multiple historical calls (already processed)
    for _ in range(5):  # Well above threshold
        response = ProcessedResponse(
            content={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "test_tool",
                                        "arguments": '{"param": "value"}',
                                    },
                                    "_already_processed": True,  # Historical
                                }
                            ]
                        }
                    }
                ]
            },
            metadata={},
        )

        # Should not raise ToolCallLoopError
        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={"config": config},
            is_streaming=False,
        )
        assert result == response

    # Now send a new tool call with same parameters
    new_response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"param": "value"}',
                                },
                                # Not marked as processed - this is new
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )

    # First new call should succeed
    result = await middleware.process(
        response=new_response,
        session_id="test-session",
        context={"config": config},
        is_streaming=False,
    )
    assert result == new_response

    # Second new call should trigger loop detection (threshold is 2)
    new_response2 = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"param": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )

    with pytest.raises(ToolCallLoopError) as exc_info:
        await middleware.process(
            response=new_response2,
            session_id="test-session",
            context={"config": config},
            is_streaming=False,
        )

    assert "Tool call loop detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_loop_detection_accuracy_with_mixed_calls() -> None:
    """Test loop detection accuracy when mixing processed and new tool calls."""
    from src.core.common.exceptions import ToolCallLoopError

    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=3,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    # Send historical calls (should be ignored)
    for _ in range(10):
        response = ProcessedResponse(
            content={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "tool_a",
                                        "arguments": "{}",
                                    },
                                    "_already_processed": True,
                                }
                            ]
                        }
                    }
                ]
            },
            metadata={},
        )
        await middleware.process(
            response=response,
            session_id="test-session",
            context={"config": config},
            is_streaming=False,
        )

    # Now send new calls with different tool (below threshold)
    for _ in range(2):
        response = ProcessedResponse(
            content={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "tool_b",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            metadata={},
        )
        # Should not raise error - below threshold
        result = await middleware.process(
            response=response,
            session_id="test-session",
            context={"config": config},
            is_streaming=False,
        )
        assert result == response

    # Now repeat tool_b one more time to trigger loop (threshold is 3)
    response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "tool_b",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )

    with pytest.raises(ToolCallLoopError):
        await middleware.process(
            response=response,
            session_id="test-session",
            context={"config": config},
            is_streaming=False,
        )


@pytest.mark.asyncio
async def test_streaming_buffer_state_feeds_loop_detector() -> None:
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=2,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )
    buffer_state = ToolCallBufferState()
    buffered_call = {
        "function": {"name": "buffered_tool", "arguments": "{}"},
        "type": "function",
    }
    buffer_state.detected_calls.append(buffered_call)

    response = ProcessedResponse(content={}, metadata={})
    context = {
        "config": config,
        "tool_call_buffer_state": buffer_state,
        "stream_id": "stream-buffer",
    }

    await middleware.process(
        response=response,
        session_id="session-buffer",
        context=context,
        is_streaming=True,
    )

    assert buffer_state.loop_cursor == 1
    assert buffered_call.get("_already_processed") is not True
