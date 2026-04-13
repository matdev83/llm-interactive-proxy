from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.backend_request_manager.canonical_post_backend_response import (
    CanonicalResponseHandle,
    PostBackendProcessingMode,
    select_post_backend_processing_mode,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.envelope_compatibility_adapter import (
    EnvelopeCompatibilityAdapter,
)
from src.core.services.post_backend_response_coordinator import (
    PostBackendResponseCoordinator,
)


def _ctx() -> ResponseProcessingContext:
    return ResponseProcessingContext(
        session_id="s1",
        backend_name="openai",
        model_name="gpt-4o-mini",
        client_os=None,
        original_request=ChatRequest(
            model="gpt-4o-mini", messages=[ChatMessage(role="user", content="hi")]
        ),
        structured_output=None,
    )


async def _async_dict_chunks(
    payload: dict[str, Any],
) -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(content=payload)


@pytest.mark.parametrize(
    ("requested_stream", "envelope", "expected"),
    [
        (
            True,
            StreamingResponseEnvelope(),
            PostBackendProcessingMode.STREAMING_HANDLER,
        ),
        (
            True,
            ResponseEnvelope(content={}),
            PostBackendProcessingMode.STREAMING_HANDLER,
        ),
        (
            False,
            ResponseEnvelope(content={}),
            PostBackendProcessingMode.STREAMING_HANDLER,
        ),
        (
            False,
            StreamingResponseEnvelope(),
            PostBackendProcessingMode.STREAMING_HANDLER,
        ),
    ],
)
def test_select_post_backend_processing_mode_matrix(
    requested_stream: bool,
    envelope: Any,
    expected: PostBackendProcessingMode,
) -> None:
    assert select_post_backend_processing_mode(requested_stream, envelope) == expected


def test_select_post_backend_stream_first_non_stream_client_streaming_envelope() -> (
    None
):
    assert (
        select_post_backend_processing_mode(False, StreamingResponseEnvelope())
        == PostBackendProcessingMode.STREAMING_HANDLER
    )


@pytest.mark.asyncio
async def test_coordinator_streaming_delegates_without_reading_request_stream_flag() -> (
    None
):
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"x")

    raw = StreamingResponseEnvelope(
        content=_src(),
        headers={"h": "1"},
        status_code=201,
        cancel_callback=AsyncMock(),
        metadata={"m": 1},
    )
    streaming_handler = MagicMock()
    streaming_handler.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=_src(),
            headers={"h": "2"},
            status_code=202,
            cancel_callback=AsyncMock(),
            metadata={"m": 2},
        )
    )
    coordinator = PostBackendResponseCoordinator(streaming_handler=streaming_handler)
    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    handle = await coordinator.from_backend_response(
        raw,
        request=request,
        context=RequestContext(headers={}, cookies={}, state=None, app_state=None),
        processing_context=_ctx(),
        processing_mode=PostBackendProcessingMode.STREAMING_HANDLER,
    )
    streaming_handler.handle.assert_awaited_once()
    assert handle.status_code == 202
    assert handle.headers == {"h": "2"}
    assert handle.cancel_callback is not None
    chunks = [c async for c in handle.stream]
    assert len(chunks) == 1
    assert chunks[0].content == b"x"


@pytest.mark.asyncio
async def test_coordinator_blocking_envelope_routes_via_streaming_handler() -> None:
    raw = ResponseEnvelope(content={"a": 1}, headers={"h": "1"}, status_code=201)

    async def _out() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"a": 2})

    streaming_handler = MagicMock()
    streaming_handler.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=_out(), headers={"h": "2"}, status_code=202
        )
    )
    coordinator = PostBackendResponseCoordinator(streaming_handler=streaming_handler)
    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    handle = await coordinator.from_backend_response(
        raw,
        request=request,
        context=RequestContext(headers={}, cookies={}, state=None, app_state=None),
        processing_context=_ctx(),
        processing_mode=PostBackendProcessingMode.STREAMING_HANDLER,
    )
    streaming_handler.handle.assert_awaited_once()
    await_args = streaming_handler.handle.await_args
    assert await_args is not None
    call_kw = await_args.kwargs
    synthetic = call_kw["stream"]
    assert isinstance(synthetic, StreamingResponseEnvelope)
    assert synthetic.content is not None
    syn_chunks = [c async for c in synthetic.content]
    assert len(syn_chunks) == 1
    assert syn_chunks[0].content == {"a": 1}
    assert handle.status_code == 202
    assert handle.headers == {"h": "2"}
    chunks = [c async for c in handle.stream]
    assert len(chunks) == 1
    assert chunks[0].content == {"a": 2}


@pytest.mark.asyncio
async def test_coordinator_streaming_envelope_uses_handler_under_canonical_mode() -> (
    None
):
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"z")

    raw = StreamingResponseEnvelope(content=_src(), headers={"h": "9"}, status_code=418)
    streaming_handler = MagicMock()
    streaming_handler.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=_src(), headers={"h": "9"}, status_code=418
        )
    )
    coordinator = PostBackendResponseCoordinator(streaming_handler=streaming_handler)
    handle = await coordinator.from_backend_response(
        raw,
        request=ChatRequest(
            model="m",
            messages=[ChatMessage(role="user", content="x")],
            stream=False,
        ),
        context=RequestContext(headers={}, cookies={}, state=None, app_state=None),
        processing_context=_ctx(),
        processing_mode=PostBackendProcessingMode.STREAMING_HANDLER,
    )
    streaming_handler.handle.assert_awaited_once()
    chunks = [c async for c in handle.stream]
    assert chunks[0].content == b"z"
    assert handle.status_code == 418
    assert handle.headers == {"h": "9"}


@pytest.mark.asyncio
async def test_adapter_requested_streaming_only_wraps_handle() -> None:
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"q")

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=203,
        media_type="text/event-stream",
        headers={"x": "y"},
        cancel_callback=None,
        usage=None,
        canonical_usage=None,
        metadata={"k": "v"},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert isinstance(env, StreamingResponseEnvelope)
    assert env.status_code == 203
    assert env.headers == {"x": "y"}
    assert env.media_type == "text/event-stream"
    out = [c async for c in cast(AsyncIterator[ProcessedResponse], env.content)]
    assert out[0].content == b"q"


@pytest.mark.asyncio
async def test_adapter_requested_non_streaming_accumulates_single_dict_chunk() -> None:
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"ok": True}, usage=None)

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=200,
        media_type="application/json",
        headers=None,
        cancel_callback=None,
        usage=None,
        canonical_usage=None,
        metadata={},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_non_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert isinstance(env, ResponseEnvelope)
    assert env.content == {"ok": True}
    assert env.media_type == "application/json"


@pytest.mark.asyncio
async def test_adapter_non_streaming_multi_chunk_merges_metadata_and_usage() -> None:
    u1 = UsageSummary(prompt_tokens=1, completion_tokens=0, total_tokens=1)
    u2 = UsageSummary(prompt_tokens=2, completion_tokens=3, total_tokens=5)
    cu = CanonicalUsageRecord(prompt_tokens=2, completion_tokens=3, total_tokens=5)

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={"partial": True},
            usage=u1,
            metadata={"a": 1, "shared": "x"},
        )
        yield ProcessedResponse(
            content={"final": True},
            usage=u2,
            metadata={"b": 2, "shared": "y"},
        )

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=200,
        media_type="application/json",
        headers={"H": "1"},
        cancel_callback=None,
        usage=u1,
        canonical_usage=cu,
        metadata={"top": True},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_non_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert isinstance(env, ResponseEnvelope)
    assert env.content == {"final": True}
    assert env.usage == u2
    assert env.canonical_usage == cu
    assert env.metadata == {"top": True, "a": 1, "shared": "y", "b": 2}


@pytest.mark.asyncio
async def test_adapter_non_streaming_reassembles_multi_chunk_string_payload() -> None:
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="Hel")
        yield ProcessedResponse(content="lo")
        yield ProcessedResponse(content="[DONE]")

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=200,
        media_type="text/plain",
        headers=None,
        cancel_callback=None,
        usage=None,
        canonical_usage=None,
        metadata={},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_non_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert isinstance(env, ResponseEnvelope)
    assert env.content == "Hello"


@pytest.mark.asyncio
async def test_adapter_non_streaming_decodes_sse_bytes_and_ignores_done_marker() -> (
    None
):
    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content=(
                b'data: {"choices":[{"message":{"content":"from-sse"}}],'
                b'"usage":{"total_tokens":7}}\n\n'
            )
        )
        yield ProcessedResponse(content=b"data: [DONE]\n\n")

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=200,
        media_type="application/json",
        headers=None,
        cancel_callback=None,
        usage=None,
        canonical_usage=None,
        metadata={"top": True},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_non_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert isinstance(env, ResponseEnvelope)
    assert env.content == {
        "choices": [{"message": {"content": "from-sse"}}],
        "usage": {"total_tokens": 7},
    }
    assert env.metadata == {"top": True}


@pytest.mark.asyncio
async def test_adapter_streaming_preserves_canonical_usage_and_cancel() -> None:
    cancel = AsyncMock()
    cu = CanonicalUsageRecord(provider_id="p", model_id="m")

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"x")

    handle = CanonicalResponseHandle(
        stream=_src(),
        status_code=204,
        media_type="text/event-stream",
        headers={"x": "y"},
        cancel_callback=cancel,
        usage=None,
        canonical_usage=cu,
        metadata={"k": "v"},
    )
    adapter = EnvelopeCompatibilityAdapter()
    env = await adapter.to_streaming(
        handle, RequestContext(headers={}, cookies={}, state=None, app_state=None)
    )
    assert env.canonical_usage == cu
    assert env.cancel_callback is cancel
    assert env.metadata == {"k": "v"}


@pytest.mark.asyncio
async def test_backend_request_manager_canonical_path_matches_legacy_streaming_result() -> (
    None
):
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"chunk")

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_src())
    )
    manager = create_backend_request_manager(backend_processor=backend_processor)

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_src(), status_code=222)
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)
    out = await manager.process_backend_request(request, "sess", ctx)
    assert isinstance(out, StreamingResponseEnvelope)
    assert out.status_code == 222
    streaming.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_request_manager_retirement_routes_raw_through_coordinator_for_streaming_client() -> (
    None
):
    """RAW envelope + retire_legacy_dual_path uses coordinator/adapter, not legacy split."""
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True}, status_code=201)
    )
    manager = create_backend_request_manager(backend_processor=backend_processor)

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        side_effect=lambda stream, **_kw: stream,
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)
    out = await manager.process_backend_request(request, "sess", ctx)
    streaming.handle.assert_awaited_once()
    assert isinstance(out, StreamingResponseEnvelope)


@pytest.mark.asyncio
async def test_backend_request_manager_always_invokes_post_backend_coordinator_regardless_of_gate() -> (
    None
):
    """Post-backend coordinator is always invoked for non-streaming canonical handling."""
    from unittest.mock import AsyncMock, patch

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"x": 1}, status_code=200)
    )
    manager = create_backend_request_manager(backend_processor=backend_processor)
    coordinator = manager._post_backend_response_coordinator

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(
            content=_async_dict_chunks({"x": 2}),
            status_code=200,
            media_type="application/json",
        )
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)
    with patch.object(
        coordinator,
        "from_backend_response",
        AsyncMock(wraps=coordinator.from_backend_response),
    ) as spy_from_backend:
        await manager.process_backend_request(request, "sess", ctx)
        spy_from_backend.assert_awaited_once()
    streaming.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_request_manager_streaming_client_blocking_backend_defaults_to_streaming_envelope() -> (
    None
):
    """Blocking backend result for a streaming client is always adapted to a streaming envelope."""
    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"sse": True}, status_code=203)
    )
    manager = create_backend_request_manager(backend_processor=backend_processor)

    streaming = cast(Any, manager._post_backend_response_coordinator._streaming_handler)
    streaming.handle = AsyncMock(
        side_effect=lambda stream, **_kw: stream,
    )

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)
    out = await manager.process_backend_request(request, "sess", ctx)
    streaming.handle.assert_awaited_once()
    assert isinstance(out, StreamingResponseEnvelope)
