"""Runtime contract: blocking backend envelopes use only the streaming handler path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_request_manager.canonical_post_backend_response import (
    PostBackendProcessingMode,
    select_post_backend_processing_mode,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.post_backend_response_coordinator import (
    PostBackendResponseCoordinator,
    response_envelope_as_single_chunk_stream,
)


def _proc_ctx() -> ResponseProcessingContext:
    return ResponseProcessingContext(
        session_id="s",
        backend_name="openai",
        model_name="m",
        client_os=None,
        original_request=ChatRequest(
            model="m", messages=[ChatMessage(role="user", content="x")]
        ),
        structured_output=None,
    )


def test_select_post_backend_processing_mode_blocking_uses_streaming_handler() -> None:
    assert (
        select_post_backend_processing_mode(False, ResponseEnvelope(content={"a": 1}))
        is PostBackendProcessingMode.STREAMING_HANDLER
    )


@pytest.mark.asyncio
async def test_response_envelope_as_single_chunk_stream_shape() -> None:
    env = ResponseEnvelope(
        content={"k": "v"},
        headers={"H": "1"},
        status_code=201,
        media_type="application/json",
        metadata={"m": 1},
    )
    wrapped = response_envelope_as_single_chunk_stream(env)
    assert isinstance(wrapped, StreamingResponseEnvelope)
    assert wrapped.status_code == 201
    assert wrapped.headers == {"H": "1"}
    assert wrapped.media_type == "application/json"
    assert wrapped.content is not None
    chunks = [c async for c in wrapped.content]
    assert len(chunks) == 1
    assert chunks[0].content == {"k": "v"}
    assert chunks[0].metadata == {
        "m": 1,
        "_synthetic_blocking_envelope": True,
    }


@pytest.mark.asyncio
async def test_coordinator_blocking_envelope_invokes_streaming_handler() -> None:
    """Blocking envelopes must always use the streaming processor (single business path)."""
    raw = ResponseEnvelope(content={"p": 1}, status_code=200)

    async def _echo(
        stream: StreamingResponseEnvelope, **_kwargs: object
    ) -> StreamingResponseEnvelope:
        return stream

    streaming = MagicMock()
    streaming.handle = AsyncMock(side_effect=_echo)
    coordinator = PostBackendResponseCoordinator(streaming_handler=streaming)
    handle = await coordinator.from_backend_response(
        raw,
        request=ChatRequest(
            model="m", messages=[ChatMessage(role="user", content="x")], stream=True
        ),
        context=RequestContext(headers={}, cookies={}, state=None, app_state=None),
        processing_context=_proc_ctx(),
        processing_mode=PostBackendProcessingMode.STREAMING_HANDLER,
    )
    streaming.handle.assert_awaited_once()
    out_chunks = [c async for c in handle.stream]
    assert len(out_chunks) == 1
    assert out_chunks[0].content == {"p": 1}


@pytest.mark.asyncio
async def test_coordinator_streaming_only_constructor() -> None:
    streaming = MagicMock()
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=_async_one_byte(),
            status_code=200,
            media_type="text/event-stream",
        )
    )
    coordinator = PostBackendResponseCoordinator(streaming_handler=streaming)
    handle = await coordinator.from_backend_response(
        ResponseEnvelope(content={"z": 1}),
        request=ChatRequest(
            model="m", messages=[ChatMessage(role="user", content="x")], stream=False
        ),
        context=RequestContext(headers={}, cookies={}, state=None, app_state=None),
        processing_context=_proc_ctx(),
        processing_mode=PostBackendProcessingMode.STREAMING_HANDLER,
    )
    streaming.handle.assert_awaited_once()
    out_chunks = [c async for c in handle.stream]
    assert len(out_chunks) == 1
    assert out_chunks[0].content == b"x"


async def _async_one_byte() -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(content=b"x")
