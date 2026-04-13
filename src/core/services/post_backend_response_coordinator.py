"""Stream-first coordinator for post-backend-response Phase-1 convergence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from src.core.domain.backend_request_manager.canonical_post_backend_response import (
    CanonicalResponseHandle,
    PostBackendProcessingMode,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.response_metadata_serialization import (
    filter_json_serializable_client_metadata,
)


class PostBackendStreamingHandlerPort(Protocol):
    """Structural contract for streaming post-backend processing (no legacy ABC)."""

    async def handle(
        self,
        stream: StreamingResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> StreamingResponseEnvelope: ...


def response_envelope_as_single_chunk_stream(
    response: ResponseEnvelope,
) -> StreamingResponseEnvelope:
    """Wrap a blocking backend envelope as a one-chunk stream for the streaming handler."""

    envelope_metadata = dict(response.metadata or {})
    envelope_metadata["_synthetic_blocking_envelope"] = True

    async def _one_chunk() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content=response.content,
            usage=response.usage,
            metadata=dict(envelope_metadata),
        )

    return StreamingResponseEnvelope(
        content=_one_chunk(),
        media_type=response.media_type,
        headers=response.headers,
        status_code=response.status_code,
        metadata=envelope_metadata,
        canonical_usage=response.canonical_usage,
        cancel_callback=None,
    )


def _canonical_handle_from_streaming_envelope(
    streaming_envelope: StreamingResponseEnvelope,
) -> CanonicalResponseHandle:
    """Build a canonical handle that replays a processed streaming envelope."""

    content_iter = streaming_envelope.content

    async def _streaming_body() -> AsyncIterator[ProcessedResponse]:
        if content_iter is None:
            return
        async for item in content_iter:
            yield item

    return CanonicalResponseHandle(
        stream=_streaming_body(),
        status_code=streaming_envelope.status_code,
        media_type=streaming_envelope.media_type,
        headers=streaming_envelope.headers,
        cancel_callback=streaming_envelope.cancel_callback,
        usage=None,
        canonical_usage=streaming_envelope.canonical_usage,
        metadata=filter_json_serializable_client_metadata(
            dict(streaming_envelope.metadata or {})
        ),
    )


class PostBackendResponseCoordinator:
    """Produces a canonical internal handle from the backend processor envelope.

    Requested streaming mode is not read from ``request``; callers must pass an
    explicit :class:`PostBackendProcessingMode` computed at the boundary.
    """

    def __init__(
        self,
        *,
        streaming_handler: PostBackendStreamingHandlerPort,
    ) -> None:
        self._streaming_handler = streaming_handler

    async def from_backend_response(
        self,
        backend_response: ResponseEnvelope | StreamingResponseEnvelope,
        *,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
        processing_mode: PostBackendProcessingMode,
    ) -> CanonicalResponseHandle:
        # Blocking envelopes always use the streaming handler (single business path).
        # ``processing_mode`` is ignored for ResponseEnvelope (always wrapped + handled).
        if isinstance(backend_response, ResponseEnvelope):
            stream_input = response_envelope_as_single_chunk_stream(backend_response)
            streaming_envelope = await self._streaming_handler.handle(
                stream=stream_input,
                request=request,
                context=context,
                processing_context=processing_context,
            )
            return _canonical_handle_from_streaming_envelope(streaming_envelope)

        if processing_mode is not PostBackendProcessingMode.STREAMING_HANDLER:
            msg = (
                "StreamingResponseEnvelope requires "
                "PostBackendProcessingMode.STREAMING_HANDLER under canonical runtime"
            )
            raise TypeError(msg)
        streaming_envelope = await self._streaming_handler.handle(
            stream=backend_response,
            request=request,
            context=context,
            processing_context=processing_context,
        )
        return _canonical_handle_from_streaming_envelope(streaming_envelope)
