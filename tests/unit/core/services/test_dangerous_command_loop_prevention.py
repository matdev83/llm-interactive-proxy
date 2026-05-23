"""
Tests for Dangerous Command Loop Prevention.

These tests verify the escalating retry mechanism that prevents infinite loops
when LLMs repeatedly attempt dangerous commands.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


def _make_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
        processing_context=None,
    )


def _create_swallowed_metadata(retry_count: int = 0) -> dict:
    """Create metadata for a swallowed dangerous command with retry count."""
    return {
        "tool_call_swallowed": True,
        "steering_message": "original steering",
        "swallowed_original_content": "dangerous output",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "git reset --hard"}}
        ],
    }


def _create_request_with_retry_count(retry_count: int) -> ChatRequest:
    """Create a request with the specified retry count."""
    extra_body = {}
    if retry_count > 0:
        # Set both keys for backward compatibility and consistency
        extra_body["_dangerous_command_retry_count"] = retry_count
        extra_body["_tool_call_reactor_retry_count"] = retry_count
        extra_body["_tool_call_reactor_retry"] = True
    return ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="do git reset --hard")],
        stream=False,
        extra_body=extra_body if extra_body else None,
    )


def _make_no_command_result() -> Any:
    from src.core.domain.processed_result import ProcessedResult

    return ProcessedResult(
        modified_messages=[],
        command_executed=False,
        command_results=[],
    )


async def async_iterator_from_list(items: list) -> AsyncIterator[Any]:
    """Helper to create async iterator from list."""
    for item in items:
        yield item


class TestDangerousCommandLoopPrevention:
    """Test the escalating retry logic for dangerous command prevention."""

    @pytest.mark.asyncio
    async def test_first_attempt_uses_first_warning_message(self) -> None:
        """First dangerous command attempt should use the first warning message."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(0)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Mock initial dangerous response then clean retry response
        backend_processor.process_backend_request.side_effect = [
            backend_response,
            ResponseEnvelope(content="safe response"),
        ]
        response_processor.process_response = AsyncMock(
            side_effect=[
                ProcessedResponse(
                    content="dangerous", metadata=_create_swallowed_metadata()
                ),
                ProcessedResponse(content="safe response", metadata={}),
            ]
        )

        await manager.process_backend_request(
            original_request, "session-1", _make_context()
        )

        # Verify the retry request was made
        assert backend_processor.process_backend_request.await_count == 2
        retry_call = backend_processor.process_backend_request.await_args
        retry_request = retry_call.kwargs["request"]

        # Check retry count is set
        # First retry: retry_count goes from 0 -> 1
        assert retry_request.extra_body["_tool_call_reactor_retry_count"] == 1
        assert retry_request.extra_body["_dangerous_command_retry_count"] == 1
        assert retry_request.extra_body["_tool_call_reactor_retry"] is True

        # Check the message contains first warning
        proxy_message = retry_request.messages[-1].content
        assert "Attempt 1/3" in proxy_message
        assert "First Warning" in proxy_message
        assert "Proxy Steering Notice" in proxy_message

    @pytest.mark.asyncio
    async def test_second_attempt_uses_second_warning_message(self) -> None:
        """Second dangerous command attempt should use stronger warning."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        # Start with retry count = 1 (meaning this is the second attempt)
        original_request = _create_request_with_retry_count(1)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Mock initial dangerous response then clean retry response
        backend_processor.process_backend_request.side_effect = [
            backend_response,
            ResponseEnvelope(content="safe response"),
        ]
        response_processor.process_response = AsyncMock(
            side_effect=[
                ProcessedResponse(
                    content="dangerous", metadata=_create_swallowed_metadata()
                ),
                ProcessedResponse(content="safe response", metadata={}),
            ]
        )

        await manager.process_backend_request(
            original_request, "session-2", _make_context()
        )

        retry_call = backend_processor.process_backend_request.await_args
        retry_request = retry_call.kwargs["request"]

        # Check retry count incremented
        assert retry_request.extra_body["_tool_call_reactor_retry_count"] == 2
        assert retry_request.extra_body["_dangerous_command_retry_count"] == 2

        # Check the message contains second warning
        proxy_message = retry_request.messages[-1].content
        assert "Attempt 2/3" in proxy_message
        assert "SECOND WARNING" in proxy_message

    @pytest.mark.asyncio
    async def test_third_attempt_uses_final_warning_message(self) -> None:
        """Third dangerous command attempt should use final warning."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(2)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Mock initial dangerous response then clean retry response
        backend_processor.process_backend_request.side_effect = [
            backend_response,
            ResponseEnvelope(content="safe response"),
        ]
        response_processor.process_response = AsyncMock(
            side_effect=[
                ProcessedResponse(
                    content="dangerous", metadata=_create_swallowed_metadata()
                ),
                ProcessedResponse(content="safe response", metadata={}),
            ]
        )

        await manager.process_backend_request(
            original_request, "session-3", _make_context()
        )

        retry_call = backend_processor.process_backend_request.await_args
        retry_request = retry_call.kwargs["request"]

        assert retry_request.extra_body["_tool_call_reactor_retry_count"] == 3
        assert retry_request.extra_body["_dangerous_command_retry_count"] == 3

        proxy_message = retry_request.messages[-1].content
        assert "Attempt 3/3" in proxy_message
        assert "FINAL WARNING" in proxy_message

    @pytest.mark.asyncio
    async def test_fourth_attempt_returns_terminal_error_non_streaming(self) -> None:
        """Fourth attempt should return terminal error instead of retrying."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(3)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Even if backend would return something, at limit we should not call it
        backend_processor.process_backend_request.return_value = backend_response
        response_processor.process_response = AsyncMock(
            return_value=ProcessedResponse(
                content="dangerous", metadata=_create_swallowed_metadata()
            )
        )

        result = await manager.process_backend_request(
            original_request,
            "session-terminal",
            _make_context(),
        )

        # Should NOT call the backend - terminal error returned immediately
        assert backend_processor.process_backend_request.await_count == 0

        # Check terminal response
        assert isinstance(result, ResponseEnvelope)
        assert "Session Terminated" in result.content
        assert "4 times" in result.content
        assert result.metadata["dangerous_command_limit_exceeded"] is True
        assert result.metadata["session_terminated"] is True
        assert result.metadata["finish_reason"] == "security_limit"

    @pytest.mark.asyncio
    async def test_fourth_attempt_returns_terminal_error_streaming(self) -> None:
        """Fourth attempt in streaming mode should return terminal error stream."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(3)
        original_request = original_request.model_copy(update={"stream": True})
        backend_response = StreamingResponseEnvelope(
            content=async_iterator_from_list(
                [
                    ProcessedResponse(
                        content="dangerous", metadata=_create_swallowed_metadata()
                    )
                ]
            )
        )

        backend_processor.process_backend_request.return_value = backend_response

        result = await manager.process_backend_request(
            original_request,
            "session-terminal-stream",
            _make_context(),
        )

        # Should NOT call the backend
        assert backend_processor.process_backend_request.await_count == 0

        # Check terminal streaming response
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None

        chunks = [chunk async for chunk in result.content]
        assert len(chunks) == 1
        assert "Session Terminated" in chunks[0].content
        assert chunks[0].metadata["dangerous_command_limit_exceeded"] is True
        assert chunks[0].metadata["session_terminated"] is True

    @pytest.mark.asyncio
    async def test_retry_counter_preserved_across_retries(self) -> None:
        """Retry counter should be properly incremented and preserved."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(0)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Simulate LLM repeating dangerous command on retry
        repeated_swallow_response = ProcessedResponse(
            content="still dangerous",
            metadata={
                "tool_call_swallowed": True,
                "steering_message": "blocked again",
                "swallowed_tool_calls": [
                    {"function": {"name": "execute_command", "arguments": "rm -rf /"}}
                ],
            },
        )

        # First call returns dangerous, then mock for recursive retry
        # Need enough responses for: initial call + retry attempts + fallback responses
        backend_processor.process_backend_request.side_effect = [
            backend_response,  # Initial call
            ResponseEnvelope(content="raw"),  # First retry
            ResponseEnvelope(content="still raw"),  # Second retry
            ResponseEnvelope(content="final raw"),  # Third retry (if needed)
        ]
        response_processor.process_response = AsyncMock(
            side_effect=[
                ProcessedResponse(
                    content="dangerous", metadata=_create_swallowed_metadata()
                ),
                repeated_swallow_response,  # First retry still dangerous
                repeated_swallow_response,  # Second retry still dangerous
                ProcessedResponse(
                    content="final raw", metadata={}
                ),  # Third retry safe (or fallback)
            ]
        )

        # This should detect the repeated swallow and recursively retry until limit
        await manager.process_backend_request(
            original_request, "session-recursive", _make_context()
        )

        # Should have made 4 backend calls (initial + 3 recursive retries: retry_count 1, 2, 3)
        # When retry_count reaches 3, next retry would be 4 which exceeds MAX (3), so it stops
        assert backend_processor.process_backend_request.await_count == 4

        # Fourth call should have retry count = 3 (the max, last retry before limit)
        fourth_call = backend_processor.process_backend_request.await_args_list[3]
        fourth_request = fourth_call.kwargs["request"]
        assert fourth_request.extra_body["_tool_call_reactor_retry_count"] == 3
        assert fourth_request.extra_body["_dangerous_command_retry_count"] == 3


class TestStreamingLoopPrevention:
    """Test loop prevention in streaming mode."""

    @pytest.mark.asyncio
    async def test_streaming_terminal_error_after_max_retries(self) -> None:
        """Streaming should return terminal error when max retries exceeded."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        # Request already at max retries
        request_at_limit = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="dangerous")],
            stream=True,
            extra_body={
                "_tool_call_reactor_retry_count": 3,
                "_dangerous_command_retry_count": 3,
                "_tool_call_reactor_retry": True,
            },
        )

        async def initial_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="still dangerous",
                metadata={
                    "tool_call_swallowed": True,
                    "steering_message": "blocked",
                },
            )

        backend_processor.process_backend_request.return_value = (
            StreamingResponseEnvelope(content=initial_stream())
        )

        result = await manager.process_backend_request(
            request_at_limit,
            "session-stream-limit",
            _make_context(),
        )

        assert isinstance(result, StreamingResponseEnvelope)
        chunks = [chunk async for chunk in result.content]

        # Should get terminal error
        assert len(chunks) == 1
        assert "Session Terminated" in chunks[0].content
        assert chunks[0].metadata["dangerous_command_limit_exceeded"] is True

    @pytest.mark.asyncio
    async def test_metadata_includes_retry_count(self) -> None:
        """Retry responses should include retry count in metadata."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_streaming_response = (
            lambda stream, _sid, **kwargs: stream
        )
        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
        )

        original_request = _create_request_with_retry_count(1)
        backend_response = ResponseEnvelope(
            content="dangerous", metadata=_create_swallowed_metadata()
        )

        # Mock initial dangerous response then clean retry response
        backend_processor.process_backend_request.side_effect = [
            backend_response,
            ResponseEnvelope(content="safe"),
        ]
        response_processor.process_response = AsyncMock(
            side_effect=[
                ProcessedResponse(
                    content="dangerous", metadata=_create_swallowed_metadata()
                ),
                ProcessedResponse(content="safe", metadata={}),
            ]
        )

        result = await manager.process_backend_request(
            original_request, "session-meta", _make_context()
        )

        assert isinstance(result, ResponseEnvelope)
        assert result.metadata["dangerous_command_retry_count"] == 2
        assert result.metadata["tool_call_reactor_retry_count"] == 2
        assert result.metadata["steering_retry_occurred"] is True
