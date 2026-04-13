"""Integration coverage for canonical backend streaming adaptation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


@pytest.mark.asyncio
async def test_non_streaming_client_streaming_backend_adapts_via_canonical_path() -> (
    None
):
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"choices": [{"message": {"content": "z"}}]})

    backend_processor = MagicMock()

    async def _proc(*, request: ChatRequest, **__: Any) -> StreamingResponseEnvelope:
        assert request.stream is True
        return StreamingResponseEnvelope(content=_src())

    backend_processor.process_backend_request = AsyncMock(side_effect=_proc)

    manager = create_backend_request_manager(backend_processor=backend_processor)

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_src(), status_code=200)
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        backend="openai",
        extensions={},
    )
    out = await manager.process_backend_request(request, "sess", ctx)
    assert isinstance(out, ResponseEnvelope)
    assert out.content == {"choices": [{"message": {"content": "z"}}]}
    backend_processor.process_backend_request.assert_awaited_once()
    streaming.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_streaming_client_decodes_streaming_backend_sse_bytes() -> None:
    async def _sse_src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content=(
                b'data: {"choices":[{"message":{"content":"from-sse"}}],'
                b'"usage":{"total_tokens":7}}\n\n'
            )
        )
        yield ProcessedResponse(content=b"data: [DONE]\n\n")

    backend_processor = MagicMock()

    async def _proc(*, request: ChatRequest, **__: Any) -> StreamingResponseEnvelope:
        assert request.stream is True
        return StreamingResponseEnvelope(content=_sse_src())

    backend_processor.process_backend_request = AsyncMock(side_effect=_proc)

    manager = create_backend_request_manager(backend_processor=backend_processor)

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_sse_src(), status_code=200)
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        backend="openai",
        extensions={},
    )
    out = await manager.process_backend_request(request, "sess", ctx)
    assert isinstance(out, ResponseEnvelope)
    assert out.content == {
        "choices": [{"message": {"content": "from-sse"}}],
        "usage": {"total_tokens": 7},
    }
    backend_processor.process_backend_request.assert_awaited_once()
    streaming.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_streaming_client_always_forces_streaming_backend_request() -> None:
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    manager = create_backend_request_manager(backend_processor=backend_processor)

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        backend="openai",
        extensions={},
    )
    await manager.process_backend_request(request, "sess", ctx)
    called = backend_processor.process_backend_request.await_args
    assert called is not None
    assert called.kwargs["request"].stream is True


@pytest.mark.asyncio
async def test_cohort_enabled_handles_blocking_backend_without_native_streaming() -> (
    None
):
    """Blocking backend responses still adapt through the canonical streaming handler."""
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": "blocking"})
    )

    manager = create_backend_request_manager(backend_processor=backend_processor)

    async def _stream_passthrough(
        *, stream: StreamingResponseEnvelope, **__: Any
    ) -> StreamingResponseEnvelope:
        return stream

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(side_effect=_stream_passthrough)

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        backend="openai",
        extensions={},
    )
    out = await manager.process_backend_request(request, "sess", ctx)
    assert isinstance(out, ResponseEnvelope)
    assert out.content == {"ok": "blocking"}
    streaming.handle.assert_awaited_once()
