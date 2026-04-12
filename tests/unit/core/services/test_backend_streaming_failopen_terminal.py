"""Unit tests: fail-open behavior and terminal error semantics (BackendStreamingResponseHandler).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.3, 7.2, 8.1
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_components import (
    IStreamingBackendResponseHandler,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    ProcessedResponse,
)

from tests.unit.core.services.backend_streaming_test_helpers import async_chunk_iterator


class TestFailOpenBehavior:
    """Tests for fail-open error handling."""

    @pytest.mark.asyncio
    async def test_continues_stream_when_middleware_fails(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should continue with original stream when middleware fails."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        # Middleware raises exception
        async def failing_stream() -> AsyncIterator[ProcessedResponse]:
            raise Exception("Middleware failed")

        mock_response_processor.process_streaming_response.return_value = (
            failing_stream()
        )

        # Act & Assert - Should not raise, but handle gracefully
        # The handler should log and continue with original stream
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Handler should still return a result (fail-open)
        assert result is not None

    @pytest.mark.asyncio
    async def test_continues_stream_when_loop_detection_fails(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should continue stream when loop detection fails."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Loop detector factory raises exception
        mock_loop_detector_factory.create.side_effect = Exception(
            "Loop detection failed"
        )

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert - Should not raise, but handle gracefully
        assert result is not None
        assert result.content is not None
        # Stream should still yield chunks
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)
        assert len(result_chunks) == 1


class TestTerminalErrorSemantics:
    """Regression tests for terminal error stream handling."""

    @pytest.mark.asyncio
    async def test_does_not_retry_when_first_chunk_is_terminal_error(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Terminal error chunks are meaningful and must bypass empty retry."""
        error_chunk = ProcessedResponse(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {
                    "message": "No auth credentials found",
                    "type": "AuthenticationError",
                    "status_code": 401,
                },
                "is_done": True,
            },
        )
        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([error_chunk])
        )
        mock_response_processor.process_streaming_response.return_value = (
            async_chunk_iterator([error_chunk])
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.status_code == 401
        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(chunks) == 1
        assert chunks[0].metadata.get("finish_reason") == "error"

    @pytest.mark.asyncio
    async def test_empty_stream_retry_stops_on_terminal_error_retry_stream(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Regression: after one empty-stream retry, terminal error must stop retries."""
        done_only_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
        retry_terminal_error_chunk = ProcessedResponse(
            content=(
                b'data: {"id":"chatcmpl-error-1","object":"chat.completion.chunk",'
                b'"choices":[{"index":0,"delta":{},"finish_reason":"error"}]}\n\n'
            ),
            metadata={"is_done": True},
        )

        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([done_only_chunk])
        )
        retry_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([retry_terminal_error_chunk])
        )
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        mock_response_processor.process_streaming_response.side_effect = [
            async_chunk_iterator([done_only_chunk]),
            async_chunk_iterator([retry_terminal_error_chunk]),
        ]

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.status_code == 502
        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(chunks) == 1
        assert chunks[0].metadata.get("is_done") is True

    @pytest.mark.asyncio
    async def test_continues_stream_when_angel_verification_fails(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should continue with original stream when Quality Verifier fails."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Angel verifier raises exception
        mock_quality_verifier_stream_verifier.verify_or_passthrough.side_effect = (
            Exception("Quality Verifier failed")
        )

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert - Should not raise, but handle gracefully
        assert result is not None
        assert result.content is not None
        # Stream should still yield chunks (fail-open)
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)
        assert len(result_chunks) == 1
