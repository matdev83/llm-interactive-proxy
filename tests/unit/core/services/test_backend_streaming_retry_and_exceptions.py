"""Unit tests: tool-call retry and stream exception recovery (BackendStreamingResponseHandler).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.3, 7.2, 8.1
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    ProcessedResponse,
)
from src.core.services.backend_request_manager.streaming_response_handler import (
    BackendStreamingResponseHandler,
)

from tests.unit.core.services.backend_streaming_test_helpers import async_chunk_iterator


class TestToolCallRetryHandling:
    """Tests for tool-call retry coordination."""

    @pytest.mark.asyncio
    async def test_delegates_to_coordinator_when_tool_call_swallowed(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should delegate to coordinator when tool call is swallowed."""
        # Arrange
        chunks = [
            ProcessedResponse(
                content="Response",
                metadata={"tool_call_swallowed": True},
            ),
        ]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [
            ProcessedResponse(
                content="Response",
                metadata={"tool_call_swallowed": True},
            ),
        ]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [
            ProcessedResponse(
                content="Retry response",
                metadata={"dangerous_command_retry_count": 1},
            ),
        ]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_tool_call_retry_coordinator.handle_streaming.return_value = retry_envelope

        # Mock loop detector and Angel verifier
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content is not None

        # Must consume stream to trigger tool-call retry logic
        # which is embedded in the async generator
        async for _ in result.content:
            pass

        mock_tool_call_retry_coordinator.handle_streaming.assert_called_once()
        call_args = mock_tool_call_retry_coordinator.handle_streaming.call_args
        if call_args.kwargs:
            assert call_args.kwargs.get("request") == base_request
            assert call_args.kwargs.get("context") == request_context

    @pytest.mark.asyncio
    async def test_returns_terminal_error_chunk_when_retry_limit_exceeded(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should return terminal error chunk when retry limit exceeded."""
        # Arrange
        chunks = [
            ProcessedResponse(
                content="Response",
                metadata={"tool_call_swallowed": True},
            ),
        ]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [
            ProcessedResponse(
                content="Response",
                metadata={"tool_call_swallowed": True},
            ),
        ]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        terminal_chunks = [
            ProcessedResponse(
                content="Session terminated",
                metadata={
                    "dangerous_command_limit_exceeded": True,
                    "session_terminated": True,
                    "is_done": True,
                    "finish_reason": "security_limit",
                },
            ),
        ]
        terminal_stream = async_chunk_iterator(terminal_chunks)
        terminal_envelope = StreamingResponseEnvelope(content=terminal_stream)
        mock_tool_call_retry_coordinator.handle_streaming.return_value = (
            terminal_envelope
        )

        # Mock loop detector and Angel verifier
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        assert result.content is not None
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)
        assert len(result_chunks) == 1


class TestStreamExceptionRecoverySemantics:
    """Tests for pre/post-meaningful stream exception recovery."""

    @pytest.mark.asyncio
    async def test_retries_stream_exception_before_meaningful_output(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Exceptions before meaningful output should retry the original request."""

        async def failing_stream() -> AsyncIterator[ProcessedResponse]:
            # Use a non-HTTP-classified error: BackendError defaults to status_code=502,
            # which pre-output recovery surfaces immediately (no empty-stream retry).
            raise RuntimeError("stream failed before output")
            yield ProcessedResponse(content="", metadata={})  # pragma: no cover

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator(retry_chunks)
        )
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        mock_response_processor.process_streaming_response.side_effect = [
            failing_stream(),
            async_chunk_iterator(retry_chunks),
        ]

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=failing_stream()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed_chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        retry_request = mock_backend_processor.process_backend_request.call_args.kwargs[
            "request"
        ]
        assert retry_request is base_request
        assert len(streamed_chunks) == 1
        assert streamed_chunks[0].content == "Retry response"

    @pytest.mark.asyncio
    async def test_rate_limit_before_meaningful_output_does_not_trigger_empty_retry(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """HTTP 429 before output must surface as an error chunk, not empty retry."""

        async def failing_stream() -> AsyncIterator[ProcessedResponse]:
            raise RateLimitExceededError(
                message="Too many requests",
                details={"headers": {"retry-after": "7"}},
            )
            yield ProcessedResponse(content="", metadata={})  # pragma: no cover

        mock_response_processor.process_streaming_response.return_value = (
            failing_stream()
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=failing_stream()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed_chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(streamed_chunks) == 1
        assert streamed_chunks[0].metadata.get("finish_reason") == "error"
        error_payload = cast(dict[str, Any], streamed_chunks[0].metadata.get("error"))
        assert error_payload["status_code"] == 429
        assert error_payload["type"] == "RateLimitExceededError"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "expected_type", "expected_status"),
        [
            (
                ServiceUnavailableError(message="Upstream temporarily unavailable"),
                "ServiceUnavailableError",
                503,
            ),
            (
                APITimeoutError(message="Upstream timed out", status_code=504),
                "APITimeoutError",
                504,
            ),
            (
                APIConnectionError(message="Connection reset", status_code=502),
                "APIConnectionError",
                502,
            ),
        ],
    )
    async def test_temporary_pre_output_errors_do_not_trigger_empty_retry(
        self,
        error: Exception,
        expected_type: str,
        expected_status: int,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Temporary backend failures should surface as terminal errors, not steering."""

        async def failing_stream() -> AsyncIterator[ProcessedResponse]:
            raise error
            yield ProcessedResponse(content="", metadata={})  # pragma: no cover

        mock_response_processor.process_streaming_response.return_value = (
            failing_stream()
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=failing_stream()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed_chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(streamed_chunks) == 1
        assert streamed_chunks[0].metadata.get("finish_reason") == "error"
        error_payload = cast(dict[str, Any], streamed_chunks[0].metadata.get("error"))
        assert error_payload["status_code"] == expected_status
        assert error_payload["type"] == expected_type

    @pytest.mark.asyncio
    async def test_emits_terminal_error_when_exception_happens_after_meaningful_output(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Exceptions after meaningful output should emit one terminal error chunk."""

        meaningful_chunk = ProcessedResponse(
            content={
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
            },
            metadata={},
        )

        async def stream_then_fail() -> AsyncIterator[ProcessedResponse]:
            yield meaningful_chunk
            raise BackendError(
                message="stream failed mid-output", backend_name="openai"
            )

        mock_response_processor.process_streaming_response.return_value = (
            stream_then_fail()
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=stream_then_fail()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(chunks) == 2
        terminal = chunks[-1]
        assert terminal.metadata.get("finish_reason") == "error"
        assert terminal.metadata.get("is_done") is True
        payload = terminal.content
        if isinstance(payload, dict):
            choices = payload.get("choices")
            assert isinstance(choices, list)
            assert choices
            first_choice = choices[0]
            assert isinstance(first_choice, dict)
            assert first_choice.get("finish_reason") == "error"
            assert isinstance(payload.get("error"), dict)
        else:
            rendered = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
            assert "finish_reason" in rendered
            assert "error" in rendered

    @pytest.mark.asyncio
    async def test_tool_call_delta_is_meaningful_and_disables_retry_on_exception(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Tool-call deltas must lock recovery into terminal-error behavior."""

        tool_call_chunk = ProcessedResponse(
            content={
                "id": "chunk-tool",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "tool_name",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            metadata={},
        )

        async def stream_then_fail() -> AsyncIterator[ProcessedResponse]:
            yield tool_call_chunk
            raise BackendError(message="tool stream interrupted", backend_name="openai")

        mock_response_processor.process_streaming_response.return_value = (
            stream_then_fail()
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=stream_then_fail()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(chunks) == 2
        assert chunks[-1].metadata.get("finish_reason") == "error"
        assert request_context.extensions.get("meaningful_output_emitted") is True

    @pytest.mark.asyncio
    async def test_reasoning_counts_as_meaningful_when_client_support_flag_enabled(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Reasoning-only output should disable retry when client marks it meaningful."""

        reasoning_chunk = ProcessedResponse(
            content={
                "id": "chunk-reasoning",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {
                            "content": "",
                            "reasoning_content": "internal reasoning token",
                        },
                        "finish_reason": None,
                    }
                ],
            },
            metadata={"_client_supports_reasoning_fields": True},
        )

        async def stream_then_fail() -> AsyncIterator[ProcessedResponse]:
            yield reasoning_chunk
            raise BackendError(
                message="reasoning stream interrupted", backend_name="openai"
            )

        mock_response_processor.process_streaming_response.return_value = (
            stream_then_fail()
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=StreamingResponseEnvelope(content=stream_then_fail()),
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(chunks) == 2
        assert chunks[-1].metadata.get("finish_reason") == "error"
        assert request_context.extensions.get("meaningful_output_emitted") is True
