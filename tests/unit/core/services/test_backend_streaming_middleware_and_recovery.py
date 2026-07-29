"""Unit tests: middleware wrapping and empty-stream recovery (BackendStreamingResponseHandler).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.3, 7.2, 8.1
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import (
    SessionCancelledError,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_work_guard_interface import IBackendWorkGuard
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    ProcessedChunkContent,
    ProcessedResponse,
)
from src.core.services.backend_request_manager.streaming_response_handler import (
    BackendStreamingResponseHandler,
)

from tests.unit.core.services.backend_streaming_test_helpers import async_chunk_iterator


def _disable_reasoning_count_for_empty_stream(request_context: RequestContext) -> None:
    request_context.app_state = SimpleNamespace(
        config=SimpleNamespace(
            session=SimpleNamespace(),
            empty_response=SimpleNamespace(count_reasoning_for_empty_stream=False),
        )
    )


class TestMiddlewareWrapping:
    """Tests for middleware wrapping."""

    @pytest.mark.asyncio
    async def test_wraps_stream_with_response_processor(
        self,
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should treat OpenAI-shaped SSE reasoning-only as empty for retry."""
        _disable_reasoning_count_for_empty_stream(request_context)
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
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should treat delta.reasoning_content-only OpenAI chunks as empty for retry."""
        _disable_reasoning_count_for_empty_stream(request_context)
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
    async def test_zai_coding_plan_with_model_suffix_counts_reasoning_as_meaningful(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
    ) -> None:
        """Backend fallback names like `zai-coding-plan:glm-5.1` must still opt into reasoning output."""

        processing_context = ResponseProcessingContext(
            session_id="session-zai-coding-plan-model-suffix",
            backend_name="zai-coding-plan:glm-5.1",
            model_name="glm-5.1",
            client_os=None,
            original_request=base_request,
            structured_output=None,
        )

        reasoning_chunk = ProcessedResponse(
            content={
                "id": "resp-zai-5-1",
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

        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([reasoning_chunk, done_chunk])
        )
        mock_response_processor.process_streaming_response.return_value = (
            async_chunk_iterator([reasoning_chunk, done_chunk])
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

        assert result.content is not None
        result_chunks = []
        async for chunk in result.content:
            result_chunks.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert len(result_chunks) == 2
        assert result_chunks[0].metadata.get("reasoning_is_output") is True

    @pytest.mark.asyncio
    async def test_reasoning_only_sse_does_not_trigger_empty_retry_when_client_opt_in(
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Handler should treat thinking-only delta as empty for retry."""
        _disable_reasoning_count_for_empty_stream(request_context)
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
    async def test_skips_empty_stream_retry_when_session_is_cancelled(
        self,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Do not issue empty-stream retry when cancellation is already known."""
        from src.core.services.backend_request_manager.streaming_response_handler import (
            BackendStreamingResponseHandler,
        )

        done_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([done_chunk])
        )

        processed_stream = async_chunk_iterator([done_chunk])
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

        cancellation_coordinator = MagicMock()
        cancellation_coordinator.ensure_not_cancelled.side_effect = (
            SessionCancelledError(
                session_key=SessionKey(protocol="http", primary_id="req-cancelled"),
                reason=ClientTerminationReason.CLIENT_DISCONNECTED,
            )
        )

        local_handler = BackendStreamingResponseHandler(
            response_processor=mock_response_processor,
            loop_detector_factory=mock_loop_detector_factory,
            quality_verifier_stream_verifier=mock_quality_verifier_stream_verifier,
            tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
            backend_processor=cast(IBackendProcessor, mock_backend_processor),
            cancellation_coordinator=cast(Any, cancellation_coordinator),
        )

        context_with_request_id = RequestContext(
            headers=request_context.headers,
            cookies=request_context.cookies,
            state=request_context.state,
            app_state=request_context.app_state,
            session_id=request_context.session_id,
            request_id="req-cancelled",
            processing_context=request_context.processing_context,
        )

        result = await local_handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=context_with_request_id,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert streamed == []

    @pytest.mark.asyncio
    async def test_stops_retry_stream_when_session_cancels_after_retry_dispatch(
        self,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Stop consuming retry stream if cancellation arrives after dispatch."""
        from src.core.services.backend_request_manager.streaming_response_handler import (
            BackendStreamingResponseHandler,
        )

        done_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([done_chunk])
        )

        processed_empty_stream = async_chunk_iterator([done_chunk])
        mock_response_processor.process_streaming_response.return_value = (
            processed_empty_stream
        )

        retry_chunks = [ProcessedResponse(content="Retry response", metadata={})]
        retry_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator(retry_chunks)
        )
        mock_backend_processor.process_backend_request.return_value = retry_envelope
        mock_response_processor.process_streaming_response.side_effect = [
            processed_empty_stream,
            async_chunk_iterator(retry_chunks),
        ]

        mock_loop_detector = MagicMock(spec=ILoopDetector)
        mock_loop_detector.process_chunk.return_value = None
        mock_loop_detector_factory.create.return_value = mock_loop_detector

        async def passthrough_stream(request, stream, context, **_kwargs):
            async for chunk in stream:
                yield chunk

        mock_quality_verifier_stream_verifier.verify_or_passthrough = passthrough_stream

        cancellation_coordinator = MagicMock()
        cancellation_coordinator.ensure_not_cancelled.side_effect = [
            None,
            SessionCancelledError(
                session_key=SessionKey(protocol="http", primary_id="req-race"),
                reason=ClientTerminationReason.CLIENT_DISCONNECTED,
            ),
        ]

        local_handler = BackendStreamingResponseHandler(
            response_processor=mock_response_processor,
            loop_detector_factory=mock_loop_detector_factory,
            quality_verifier_stream_verifier=mock_quality_verifier_stream_verifier,
            tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
            backend_processor=cast(IBackendProcessor, mock_backend_processor),
            cancellation_coordinator=cast(Any, cancellation_coordinator),
        )

        context_with_request_id = RequestContext(
            headers=request_context.headers,
            cookies=request_context.cookies,
            state=request_context.state,
            app_state=request_context.app_state,
            session_id=request_context.session_id,
            request_id="req-race",
            processing_context=request_context.processing_context,
        )

        result = await local_handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=context_with_request_id,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed.append(chunk)

        mock_backend_processor.process_backend_request.assert_called_once()
        assert streamed == []

    @pytest.mark.asyncio
    async def test_skips_empty_stream_retry_when_guard_reports_cancelled(
        self,
        mock_response_processor: AsyncMock,
        mock_backend_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        mock_tool_call_retry_coordinator: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Guard-level cancellation should prevent empty-stream retry dispatch."""
        from src.core.services.backend_request_manager.streaming_response_handler import (
            BackendStreamingResponseHandler,
        )

        done_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
        stream_envelope = StreamingResponseEnvelope(
            content=async_chunk_iterator([done_chunk])
        )

        processed_stream = async_chunk_iterator([done_chunk])
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

        backend_work_guard = MagicMock(spec=IBackendWorkGuard)
        backend_work_guard.ensure_session_active.return_value = SessionKey(
            protocol="http", primary_id="req-guard-stream-cancelled"
        )
        backend_work_guard.is_cancelled.return_value = True

        local_handler = BackendStreamingResponseHandler(
            response_processor=mock_response_processor,
            loop_detector_factory=mock_loop_detector_factory,
            quality_verifier_stream_verifier=mock_quality_verifier_stream_verifier,
            tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
            backend_processor=cast(IBackendProcessor, mock_backend_processor),
            backend_work_guard=cast(Any, backend_work_guard),
        )

        context_with_request_id = RequestContext(
            headers=request_context.headers,
            cookies=request_context.cookies,
            state=request_context.state,
            app_state=request_context.app_state,
            session_id=request_context.session_id,
            request_id="req-guard-stream-cancelled",
            processing_context=request_context.processing_context,
        )

        result = await local_handler.handle(
            stream=stream_envelope,
            request=base_request,
            context=context_with_request_id,
            processing_context=processing_context,
        )

        assert result.content is not None
        streamed: list[ProcessedResponse] = []
        async for chunk in result.content:
            streamed.append(chunk)

        mock_backend_processor.process_backend_request.assert_not_called()
        assert streamed == []

    @pytest.mark.asyncio
    async def test_treats_reasoning_metadata_as_empty_for_retry(
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
        handler: BackendStreamingResponseHandler,
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
        handler: BackendStreamingResponseHandler,
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
        assert terminal.content not in ("", b"")
        if isinstance(terminal.content, bytes):
            rendered = terminal.content.decode("utf-8", errors="replace")
        else:
            rendered = str(terminal.content)
        assert "error" in rendered
        assert terminal.metadata.get("finish_reason") == "error"
        assert terminal.metadata.get("is_done") is True
        assert terminal.metadata.get("session_id") == "test-session-123"
        err = terminal.metadata.get("error")
        assert isinstance(err, dict)
        assert err.get("type") in {"BackendError", "empty_stream_after_retries"}
        assert err.get("code") == "empty_stream_after_retries"
        assert "message" in err
        warn = terminal.metadata.get("proxy_warning")
        assert isinstance(warn, dict)
        warn_dict = cast(dict, warn)
        assert warn_dict.get("type") == "empty_stream_after_retries"

        mock_backend_processor.process_backend_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_code_content_with_error_string_not_flagged_as_terminal_error(
        self,
        handler: BackendStreamingResponseHandler,
        mock_response_processor: AsyncMock,
        mock_loop_detector_factory: MagicMock,
        mock_quality_verifier_stream_verifier: AsyncMock,
        base_request: ChatRequest,
        request_context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> None:
        """Code output containing 'error' substring should yield as normal content."""
        code_chunk = ProcessedResponse(
            content='data: {"choices":[{"delta":{"content":"print(\\"error log\\")"},"finish_reason":null}]}\n\n',
            metadata={},
        )
        input_stream = async_chunk_iterator([code_chunk])
        stream_envelope = StreamingResponseEnvelope(content=input_stream)
        mock_response_processor.process_streaming_response.return_value = (
            async_chunk_iterator([code_chunk])
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

        assert result.content is not None
        chunks = [ch async for ch in result.content]
        assert len(chunks) == 1
        assert "error log" in str(chunks[0].content)
