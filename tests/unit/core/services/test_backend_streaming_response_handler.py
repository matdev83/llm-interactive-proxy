"""
Unit tests for BackendStreamingResponseHandler.

Tests cover streaming response processing including:
- Response processor middleware wrapping
- Empty-stream recovery with retry prompts
- Empty-stream exhaustion error handling
- Tool-call retry coordination
- Loop detection and cancellation
- Quality Verifier pass-through and replacement
- Steering replacement marker preservation
- Metadata attachment (session_id, original_request, client_os)
- Fail-open error handling

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.3, 7.2, 8.1
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    ILoopDetectorFactory,
    IQualityVerifierStreamVerifier,
    IStreamingBackendResponseHandler,
    IToolCallRetryCoordinator,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedChunkContent,
    ProcessedResponse,
)
from src.loop_detection.event import LoopDetectionEvent


@pytest.fixture
def mock_response_processor() -> IResponseProcessor:
    """Create a mock response processor."""
    mock = AsyncMock(spec=IResponseProcessor)
    return mock


@pytest.fixture
def mock_loop_detector_factory() -> ILoopDetectorFactory:
    """Create a mock loop detector factory."""
    mock = MagicMock(spec=ILoopDetectorFactory)
    return mock


@pytest.fixture
def mock_quality_verifier_stream_verifier() -> IQualityVerifierStreamVerifier:
    """Create a mock Angel stream verifier."""
    mock = AsyncMock(spec=IQualityVerifierStreamVerifier)

    async def passthrough(request, stream, context):
        async for chunk in stream:
            yield chunk

    mock.verify_or_passthrough.side_effect = passthrough
    return mock


@pytest.fixture
def mock_tool_call_retry_coordinator() -> IToolCallRetryCoordinator:
    """Create a mock tool-call retry coordinator."""
    mock = AsyncMock(spec=IToolCallRetryCoordinator)
    return mock


@pytest.fixture
def mock_backend_processor() -> IBackendProcessor:
    """Create a mock backend processor."""
    mock = AsyncMock(spec=IBackendProcessor)
    return mock


@pytest.fixture
def handler(
    mock_response_processor: IResponseProcessor,
    mock_loop_detector_factory: ILoopDetectorFactory,
    mock_quality_verifier_stream_verifier: IQualityVerifierStreamVerifier,
    mock_tool_call_retry_coordinator: IToolCallRetryCoordinator,
    mock_backend_processor: IBackendProcessor,
) -> IStreamingBackendResponseHandler:
    """Create a BackendStreamingResponseHandler instance."""
    from src.core.services.backend_request_manager.streaming_response_handler import (
        BackendStreamingResponseHandler,
    )

    return BackendStreamingResponseHandler(
        response_processor=mock_response_processor,
        loop_detector_factory=mock_loop_detector_factory,
        quality_verifier_stream_verifier=mock_quality_verifier_stream_verifier,
        tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
        backend_processor=mock_backend_processor,
    )


@pytest.fixture
def base_request() -> ChatRequest:
    """Create a base chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )


@pytest.fixture
def request_context() -> RequestContext:
    """Create a request context for testing."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        processing_context=ProcessingContext(),
    )


@pytest.fixture
def processing_context(base_request: ChatRequest) -> ResponseProcessingContext:
    """Create a processing context for testing."""
    return ResponseProcessingContext(
        session_id="test-session-123",
        backend_name="openai",
        model_name="gpt-4",
        client_os="Windows",
        original_request=base_request,
        structured_output=None,
    )


async def async_chunk_iterator(
    chunks: list[ProcessedResponse],
) -> AsyncIterator[ProcessedResponse]:
    """Helper to create async iterator from list."""
    for chunk in chunks:
        yield chunk


class TestMiddlewareWrapping:
    """Tests for middleware wrapping."""

    @pytest.mark.asyncio
    async def test_wraps_stream_with_response_processor(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should wrap stream with response processor middleware."""
        # Arrange
        chunks = [
            ProcessedResponse(content="Hello", metadata={}),
            ProcessedResponse(content=" world", metadata={}),
        ]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_chunks = [
            ProcessedResponse(content="Hello", metadata={"processed": True}),
            ProcessedResponse(content=" world", metadata={"processed": True}),
        ]
        processed_stream = async_chunk_iterator(processed_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Mock Angel verifier to pass through (return the stream directly, not consume it)
        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        # Mock loop detector factory to return a detector that never detects loops
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
        mock_response_processor.process_streaming_response.assert_called_once()
        call_args = mock_response_processor.process_streaming_response.call_args

        # process_streaming_response signature: (response_iterator, session_id, context=None)
        # Handler now passes RequestContext directly instead of middleware_context dict
        # So first arg is stream, second is session_id (positional), third is context (positional)
        assert len(call_args[0]) >= 3
        session_id_arg = call_args[0][1]  # Second positional arg
        context_arg = call_args[0][2]  # Third positional arg (RequestContext)

        assert session_id_arg == "test-session-123"
        from src.core.domain.request_context import RequestContext

        assert isinstance(context_arg, RequestContext)
        assert context_arg.session_id == "test-session-123"
        assert context_arg.backend == "openai"
        assert context_arg.effective_model == "gpt-4"
        assert (
            context_arg.original_request == base_request
            or context_arg.domain_request == base_request
        )

        # Verify stream content
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)
        assert len(result_chunks) == 2

    @pytest.mark.asyncio
    async def test_preserves_envelope_properties(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should preserve media_type, headers, and cancel_callback."""

        # Arrange
        async def cancel_cb() -> None:
            pass

        chunks = [ProcessedResponse(content="Hello", metadata={})]
        input_stream = async_chunk_iterator(chunks)
        stream_envelope = StreamingResponseEnvelope(
            content=input_stream,
            media_type="text/event-stream",
            headers={"X-Custom": "value"},
            status_code=413,
            cancel_callback=cancel_cb,
        )

        processed_stream = async_chunk_iterator(chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        # Act
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        # Assert
        assert result.media_type == "text/event-stream"
        assert result.headers == {"X-Custom": "value"}
        assert result.status_code == 413
        assert result.cancel_callback == cancel_cb


class TestEmptyStreamRecovery:
    """Tests for empty stream recovery."""

    @pytest.mark.asyncio
    async def test_retries_empty_stream_with_recovery_prompt(
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
        """Handler should retry empty streams with recovery prompt."""
        # Arrange
        # Empty stream (no chunks) triggers recovery retry
        empty_chunks: list[ProcessedResponse] = []
        empty_stream = async_chunk_iterator(empty_chunks)
        stream_envelope = StreamingResponseEnvelope(content=empty_stream)

        # Response processor returns empty stream (will be detected as empty by gate_empty_stream)
        processed_empty_stream = async_chunk_iterator(empty_chunks)
        mock_response_processor.process_streaming_response.return_value = (
            processed_empty_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        # Second call returns processed retry stream (with meaningful content)
        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_empty_stream,
            processed_retry_stream,
        ]

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

        # Must consume stream before asserting call to backend processor
        # because recovery logic is inside the async generator
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 1
        assert result_chunks[0].content == "Retry response"

    @pytest.mark.asyncio
    async def test_retries_reasoning_only_stream(
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
        """Handler should treat reasoning-only streams as empty for retry."""
        reasoning_chunk = ProcessedResponse(
            content={
                "id": "resp-1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": ""}, "finish_reason": None}],
            },
            metadata={"accumulated_reasoning": "internal"},
        )
        input_stream = async_chunk_iterator([reasoning_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert result_chunks[1].content == "Retry response"

    @pytest.mark.asyncio
    async def test_retries_reasoning_only_sse_stream(
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
        """Handler should treat OpenAI-shaped SSE reasoning-only as empty for retry."""
        reasoning_sse = (
            b'data: {"id":"resp-sse-1","object":"chat.completion.chunk","choices":'
            b'[{"delta":{"content":"","reasoning_content":"internal"},"finish_reason":null}]}'
            b"\n\n"
        )
        reasoning_chunk = ProcessedResponse(content=reasoning_sse, metadata={})

        input_stream = async_chunk_iterator([reasoning_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert result_chunks[1].content == "Retry response"

    @pytest.mark.asyncio
    async def test_retries_openai_reasoning_content_delta_dict(
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
        """Handler should treat delta.reasoning_content-only OpenAI chunks as empty for retry."""
        reasoning_chunk = ProcessedResponse(
            content={
                "id": "resp-rc-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {"content": "", "reasoning_content": "internal"},
                        "finish_reason": None,
                    }
                ],
            },
            metadata={},
        )

        input_stream = async_chunk_iterator([reasoning_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert result_chunks[1].content == "Retry response"

    @pytest.mark.asyncio
    async def test_qwen_oauth_reasoning_content_counts_as_meaningful_output(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
    ) -> None:
        """qwen-oauth streams often emit reasoning_content without content.

        For qwen-oauth we treat reasoning output as meaningful to avoid empty-stream
        retries and to enable downstream suppression of duplicated reasoning aliases.
        """

        processing_context = ResponseProcessingContext(
            session_id="session-qwen-oauth",
            backend_name="qwen-oauth",
            model_name="coder-model",
            client_os=None,
            original_request=base_request,
            structured_output=None,
        )

        reasoning_chunk = ProcessedResponse(
            content={
                "id": "resp-qwen-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {"content": "", "reasoning_content": "internal"},
                        "finish_reason": None,
                    }
                ],
            },
            metadata={},
        )
        done_chunk = ProcessedResponse(content="data: [DONE]\n\n", metadata={})

        input_stream = async_chunk_iterator([reasoning_chunk, done_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk, done_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert (
            result_chunks[0].metadata.get("_client_supports_reasoning_fields") is True
        )
        assert result_chunks[0].metadata.get("reasoning_is_output") is True
        assert result_chunks[0].metadata.get("_suppress_reasoning_fields") is True
        assert result_chunks[0].metadata.get("_keep_reasoning_content") is True

    @pytest.mark.asyncio
    async def test_zai_coding_plan_reasoning_content_counts_as_meaningful_output(
        self,
        handler: IStreamingBackendResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
    ) -> None:
        """zai-coding-plan can stream reasoning-only chunks before user content.

        Treat these chunks as meaningful so empty-stream recovery does not fire
        when the client expects reasoning fields.
        """

        processing_context = ResponseProcessingContext(
            session_id="session-zai-coding-plan",
            backend_name="zai-coding-plan",
            model_name="glm-4.7",
            client_os=None,
            original_request=base_request,
            structured_output=None,
        )

        reasoning_chunk = ProcessedResponse(
            content={
                "id": "resp-zai-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {"content": "", "reasoning_content": "internal"},
                        "finish_reason": None,
                    }
                ],
            },
            metadata={},
        )
        done_chunk = ProcessedResponse(content="data: [DONE]\n\n", metadata={})

        input_stream = async_chunk_iterator([reasoning_chunk, done_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk, done_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert (
            result_chunks[0].metadata.get("_client_supports_reasoning_fields") is True
        )
        assert result_chunks[0].metadata.get("reasoning_is_output") is True
        assert result_chunks[0].metadata.get("_suppress_reasoning_fields") is True
        assert result_chunks[0].metadata.get("_keep_reasoning_content") is True

    @pytest.mark.asyncio
    async def test_reasoning_only_sse_does_not_trigger_empty_retry_when_client_opt_in(
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
        """Reasoning-only SSE should be treated as meaningful output.

        Some providers emit long stretches of `delta.reasoning_content` with empty
        `delta.content`. The empty-stream retry gate must treat this as meaningful
        to avoid pointless retries.
        """
        reasoning_sse = (
            b'data: {"id":"resp-sse-opencode","object":"chat.completion.chunk","choices":'
            b'[{"delta":{"content":"","reasoning_content":"internal"},"finish_reason":null}]}'
            b"\n\n"
        )
        reasoning_chunk = ProcessedResponse(content=reasoning_sse, metadata={})

        input_stream = async_chunk_iterator([reasoning_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        opt_in_context = RequestContext(
            headers={
                "x-llmproxy-reasoning-mode": "passthrough",
                "x-llmproxy-reasoning-meaningful": "true",
            },
            cookies=request_context.cookies,
            state=request_context.state,
            app_state=request_context.app_state,
            session_id=request_context.session_id,
            processing_context=request_context.processing_context,
        )

        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=opt_in_context,
            processing_context=processing_context,
        )

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        assert len(result_chunks) == 1
        assert result_chunks[0].content == reasoning_chunk.content
        assert (
            result_chunks[0].metadata.get("_client_supports_reasoning_fields") is True
        )
        assert result_chunks[0].metadata.get("_suppress_reasoning_fields") is not True
        assert result_chunks[0].metadata.get("_keep_reasoning_content") is None
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_openai_sse_content_prevents_retry(
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
        """Handler should not retry when OpenAI-shaped SSE contains delta.content."""
        content_sse = (
            'data: {"id":"resp-sse-2","object":"chat.completion.chunk","choices":'
            '[{"delta":{"content":"Hi"},"finish_reason":null}]}'
            "\n\n"
        )
        content_chunk = ProcessedResponse(content=content_sse, metadata={})
        input_stream = async_chunk_iterator([content_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([content_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(result_chunks) == 1
        assert result_chunks[0].content == content_sse

    @pytest.mark.asyncio
    async def test_done_only_stream_triggers_retry(
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
        """A lone `data: [DONE]` must not bypass empty-stream recovery."""
        done_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
        input_stream = async_chunk_iterator([done_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([done_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        # Terminal markers are buffered; only the retry output is returned.
        assert len(result_chunks) == 1
        assert result_chunks[0].content == "Retry response"

    @pytest.mark.asyncio
    async def test_treats_thinking_delta_as_empty_for_retry(
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
        """Handler should treat thinking-only delta as empty for retry."""
        thinking_chunk = ProcessedResponse(
            content={
                "id": "resp-2",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {"content": "", "thinking": "Planning response."},
                        "finish_reason": None,
                    }
                ],
            }
        )
        input_stream = async_chunk_iterator([thinking_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([thinking_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == thinking_chunk.content
        assert result_chunks[1].content == "Retry response"

    @pytest.mark.asyncio
    async def test_treats_reasoning_metadata_as_empty_for_retry(
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
        """Handler should treat reasoning-only metadata as empty for retry."""
        reasoning_chunk = ProcessedResponse(
            content="",
            metadata={"reasoning_content": "Working through the steps."},
        )
        input_stream = async_chunk_iterator([reasoning_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([reasoning_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_stream = async_chunk_iterator(retry_chunks)
        retry_envelope = StreamingResponseEnvelope(content=retry_stream)
        mock_backend_processor.process_backend_request.return_value = retry_envelope

        processed_retry_stream = async_chunk_iterator(retry_chunks)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_stream,
            processed_retry_stream,
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

        assert result is not None
        assert result.content is not None

        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert len(result_chunks) == 2
        assert result_chunks[0].content == reasoning_chunk.content
        assert result_chunks[1].content == "Retry response"

    @pytest.mark.asyncio
    async def test_terminal_chunk_skips_empty_stream_retry(
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
        """Handler should not retry when stream ends with a terminal chunk."""
        terminal_content = cast(
            ProcessedChunkContent,
            {
                "id": "loop-detector-123",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": "loop-detector",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": ""},
                        "finish_reason": "cancelled",
                    }
                ],
            },
        )
        terminal_chunk = ProcessedResponse(
            content=terminal_content,
            metadata={"is_cancellation": True, "is_done": True},
        )
        input_stream = async_chunk_iterator([terminal_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)

        processed_stream = async_chunk_iterator([terminal_chunk])
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
        assert result_chunks[0].metadata.get("is_cancellation") is True
        mock_backend_processor.process_backend_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_terminal_error_chunk_when_empty_stream_retry_limit_exceeded(
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
        """Handler emits a terminal error chunk when empty stream retry limit exceeded."""
        # Arrange
        # Empty stream (no chunks) should trigger retry exhaustion
        empty_chunks: list[ProcessedResponse] = []
        empty_stream = async_chunk_iterator(empty_chunks)
        stream_envelope = StreamingResponseEnvelope(content=empty_stream)

        # Response processor returns empty stream
        processed_empty_stream = async_chunk_iterator(empty_chunks)
        # First call returns empty, second call also returns empty (exceeds limit)
        mock_response_processor.process_streaming_response.side_effect = [
            processed_empty_stream,
            processed_empty_stream,
        ]

        # Mock backend processor to return empty stream on retry
        retry_empty_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator(empty_chunks)
        )
        mock_backend_processor.process_backend_request.return_value = (
            retry_empty_envelope
        )

        # Mock loop detector and Angel verifier
        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        # Act & Assert
        result = await handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=request_context,
            processing_context=processing_context,
        )

        assert result.content is not None
        chunks: list[ProcessedResponse] = []
        async for chunk in result.content:
            chunks.append(chunk)

        assert chunks
        terminal = chunks[-1]
        assert terminal.content in ("", b"")
        assert terminal.metadata.get("finish_reason") == "error"
        assert terminal.metadata.get("is_done") is True
        assert terminal.metadata.get("session_id") == "test-session-123"
        err = terminal.metadata.get("error")
        assert isinstance(err, dict)
        assert err.get("type") == "empty_stream_after_retries"
        assert "message" in err
        warn = terminal.metadata.get("proxy_warning")
        assert isinstance(warn, dict)
        warn_dict = cast(dict, warn)
        assert warn_dict.get("type") == "empty_stream_after_retries"

        mock_backend_processor.process_backend_request.assert_called_once()


class TestToolCallRetryHandling:
    """Tests for tool-call retry coordination."""

    @pytest.mark.asyncio
    async def test_delegates_to_coordinator_when_tool_call_swallowed(
        self,
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        assert result_chunks[0].metadata.get("dangerous_command_limit_exceeded") is True
        assert result_chunks[0].metadata.get("session_terminated") is True


class TestLoopDetectionCancellation:
    """Tests for loop detection and cancellation."""

    @pytest.mark.asyncio
    async def test_emits_cancellation_chunk_when_loop_detected(
        self,
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
        handler: IStreamingBackendResponseHandler,
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
