"""Unit tests: loop detection, quality verifier, metadata (BackendStreamingResponseHandler).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.3, 7.2, 8.1
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
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
from src.loop_detection.event import LoopDetectionEvent

from tests.unit.core.services.backend_streaming_test_helpers import async_chunk_iterator


class TestLoopDetectionCancellation:
    """Tests for loop detection and cancellation."""

    @pytest.mark.asyncio
    async def test_emits_cancellation_chunk_when_loop_detected(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should emit cancellation chunk when loop detected."""
        # Arrange
        chunks = [
            ProcessedResponse(content="Hello", metadata={}),
            ProcessedResponse(content="Hello", metadata={}),  # Repeated
        ]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [
            ProcessedResponse(content="Hello", metadata={}),
            ProcessedResponse(content="Hello", metadata={}),
        ]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        loop_event = LoopDetectionEvent(
            pattern="Hello",
            repetition_count=2,
            pattern_length=5,
            total_length=10,
            confidence=0.9,
            buffer_content="HelloHello",
            timestamp=1234567890.0,
        )
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.side_effect = [None, loop_event]
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
        # Should have cancellation chunk
        assert len(result_chunks) >= 1
        cancellation_chunk = result_chunks[-1]
        assert cancellation_chunk.metadata.get("loop_detected") is True
        assert cancellation_chunk.metadata.get("is_cancellation") is True

    @pytest.mark.asyncio
    async def test_invokes_cancel_callback_when_loop_detected(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should invoke cancel_callback when loop detected."""
        # Arrange
        cancel_called = False

        async def cancel_callback() -> None:
            nonlocal cancel_called
            cancel_called = True

        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(
            content=input_stream,
            cancel_callback=cancel_callback,
        )

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        loop_event = LoopDetectionEvent(
            pattern="Hello",
            repetition_count=2,
            pattern_length=5,
            total_length=10,
            confidence=0.9,
            buffer_content="HelloHello",
            timestamp=1234567890.0,
        )
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = loop_event
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
        # Consume stream to trigger loop detection
        async for _ in result.content:
            pass
        assert cancel_called is True


class TestAngelVerification:
    """Tests for Quality Verifier."""

    @pytest.mark.asyncio
    async def test_passes_through_original_stream_when_verification_disabled(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should pass through original stream when Quality Verifier disabled."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Angel verifier returns original stream (pass-through)
        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        # Mock loop detector
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result is not None
        # verify_or_passthrough was called (it's now a function, not a mock)
        # We can verify by checking the result stream works
        assert result.content is not None
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)
        assert len(result_chunks) == 1

    @pytest.mark.asyncio
    async def test_returns_corrected_output_when_steering_decision_occurs(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should return corrected output when steering decision occurs."""
        # Arrange
        chunks = [ProcessedResponse(content="Original", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Original", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        corrected_chunks = [
            ProcessedResponse(
                content="Corrected",
                metadata={"_steering_replacement": True},
            ),
        ]
        corrected_stream = async_chunk_iterator(corrected_chunks)

        async def corrected_stream_gen(request, stream, context, request_context=None):
            async for chunk in corrected_stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = (
            corrected_stream_gen
        )

        # Mock loop detector
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

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
        assert result_chunks[0].content == "Corrected"
        assert result_chunks[0].metadata.get("_steering_replacement") is True


class TestMetadataAttachment:
    """Tests for metadata attachment."""

    @pytest.mark.asyncio
    async def test_attaches_session_id_to_chunks(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should attach session_id to streaming chunks."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
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
        assert result_chunks[0].metadata.get("session_id") == "test-session-123"

    @pytest.mark.asyncio
    async def test_attaches_original_request_to_chunks(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should attach original_request to streaming chunks."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
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
        assert "original_request" in result_chunks[0].metadata

    @pytest.mark.asyncio
    async def test_attaches_client_os_to_chunks(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should attach client_os to streaming chunks."""
        # Arrange
        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [ProcessedResponse(content="Hello", metadata={})]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Mock loop detector and Angel verifier
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, request_context=None):
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
        # Check metadata dict directly, not via get() which might return coroutine from mock
        metadata = result_chunks[0].metadata
        assert isinstance(metadata, dict)
        assert metadata.get("client_os") == "Windows"

    @pytest.mark.asyncio
    async def test_resolves_client_reasoning_policy_once_per_stream(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        chunks = [
            ProcessedResponse(content="first", metadata={}),
            ProcessedResponse(content="second", metadata={}),
        ]
        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator(chunks)
        )
        mock_response_processor.process_streaming_response.return_value = (
            async_chunk_iterator(chunks)
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        request_context.headers = {"user-agent": "unit-test-agent"}
        call_counter = {"count": 0}

        def _resolve_policy(*_args, **_kwargs):
            call_counter["count"] += 1
            return SimpleNamespace(
                reasoning_counts_as_meaningful=True,
                reasoning_mode="drop",
            )

        monkeypatch.setattr(
            "src.core.common.client_compatibility.resolve_client_reasoning_policy",
            _resolve_policy,
        )

        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        emitted = [chunk async for chunk in result.content]
        assert len(emitted) == 2
        assert call_counter["count"] == 1
        assert emitted[0].metadata.get("_client_supports_reasoning_fields") is True
        assert emitted[0].metadata.get("_suppress_reasoning_fields") is True
