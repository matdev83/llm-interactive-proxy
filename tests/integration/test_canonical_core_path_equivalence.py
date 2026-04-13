"""Integration checks for the canonical BackendRequestManager post-backend path.

Historically this module compared migration-gate ON vs OFF; runtime now always
selects the canonical core path. Tests assert stable externally observable
behavior (transport, errors, dedup, retries) under that single path.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic.types import JsonValue
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.migration_gate_service import MigrationGateService

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


def _ctx() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        extensions={},
    )


async def _collect_stream(
    envelope: StreamingResponseEnvelope,
) -> list[ProcessedResponse]:
    if envelope.content is None:
        return []
    return [c async for c in envelope.content]


def _streaming_observables(
    envelope: StreamingResponseEnvelope,
) -> dict[str, Any]:
    return {
        "status_code": envelope.status_code,
        "headers": envelope.headers,
        "media_type": envelope.media_type,
        "has_cancel": envelope.cancel_callback is not None,
        "canonical_usage": envelope.canonical_usage,
        "metadata": envelope.metadata,
    }


def _non_streaming_observables(envelope: ResponseEnvelope) -> dict[str, Any]:
    return {
        "status_code": envelope.status_code,
        "headers": envelope.headers,
        "media_type": envelope.media_type,
        "content": envelope.content,
        "usage": envelope.usage,
        "canonical_usage": envelope.canonical_usage,
        "metadata": envelope.metadata,
    }


async def _run_manager_streaming(
    manager: BackendRequestManager,
    *,
    request: ChatRequest,
    session_id: str = "sess",
    context: RequestContext | None = None,
) -> tuple[list[ProcessedResponse], dict[str, Any]]:
    ctx = context or _ctx()
    out = await manager.process_backend_request(request, session_id, ctx)
    assert isinstance(out, StreamingResponseEnvelope)
    chunks = await _collect_stream(out)
    return chunks, _streaming_observables(out)


async def _run_manager_non_streaming(
    manager: BackendRequestManager,
    *,
    request: ChatRequest,
    session_id: str = "sess",
    context: RequestContext | None = None,
) -> dict[str, Any]:
    ctx = context or _ctx()
    out = await manager.process_backend_request(request, session_id, ctx)
    assert isinstance(out, ResponseEnvelope)
    return _non_streaming_observables(out)


def _configure_gate(
    manager: BackendRequestManager,
    *,
    diagnostics: bool = False,
    legacy_streaming_client_blocking_envelope: bool = False,
) -> None:
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=diagnostics,
        legacy_streaming_client_blocking_envelope=legacy_streaming_client_blocking_envelope,
    )


def _meta(data: dict[str, Any]) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], data)


def _async_iter_from_list(
    items: list[ProcessedResponse],
) -> AsyncIterator[ProcessedResponse]:
    async def _it() -> AsyncIterator[ProcessedResponse]:
        for it in items:
            yield it

    return _it()


@pytest.mark.asyncio
async def test_streaming_transport_observables_canonical_path() -> None:
    """SSE-shaped chunks, status, headers, media_type, cancel surface as expected."""

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content=b'data: {"choices":[{"index":0,"delta":{"content":"x"}}]}\n\n'
        )
        yield ProcessedResponse(content=b"data: [DONE]\n\n")

    cancel = AsyncMock()

    async def _handle(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(
            content=stream.content,
            status_code=201,
            media_type="text/event-stream",
            headers={"X-Test": "1"},
            cancel_callback=cancel,
            metadata={"m": 2},
        )

    backend_processor = MagicMock()

    async def _fresh_envelope(*_: Any, **__: Any) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_src())

    backend_processor.process_backend_request = AsyncMock(side_effect=_fresh_envelope)

    base = create_backend_request_manager(backend_processor=backend_processor)
    streaming = cast(Any, base._post_backend_response_coordinator)._streaming_handler
    streaming.handle = AsyncMock(side_effect=_handle)

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    _configure_gate(base)
    chunks, meta = await _run_manager_streaming(base, request=request)

    assert len(chunks) == 2
    assert meta["status_code"] == 201
    assert meta["media_type"] == "text/event-stream"
    assert meta["headers"] == {"X-Test": "1"}
    assert meta["has_cancel"] is True
    assert meta["metadata"] == {"m": 2}
    assert streaming.handle.await_count == 1


@pytest.mark.asyncio
async def test_non_streaming_schema_usage_canonical_path() -> None:
    """JSON body, usage, headers, and metadata from the post-backend handler."""
    body = {"id": "chatcmpl-test", "choices": [{"message": {"content": "ok"}}]}
    usage = UsageSummary(prompt_tokens=3, completion_tokens=5, total_tokens=8)

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"raw": True})
    )

    base = create_backend_request_manager(backend_processor=backend_processor)
    streaming = cast(Any, base._post_backend_response_coordinator)._streaming_handler

    async def _stream_handle(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        async def _chunks() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content=cast(dict[str, JsonValue], body),
                usage=usage,
                metadata={"meta": True},
            )

        return StreamingResponseEnvelope(
            content=_chunks(),
            status_code=202,
            media_type="application/json",
            headers={"H": "v"},
            metadata={"meta": True},
        )

    streaming.handle = AsyncMock(side_effect=_stream_handle)

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )

    _configure_gate(base)
    obs = await _run_manager_non_streaming(base, request=request)

    assert obs["status_code"] == 202
    assert obs["content"] == body
    assert obs["usage"] == usage
    assert obs["headers"] == {"H": "v"}
    assert obs["metadata"] == {"meta": True}
    assert streaming.handle.await_count == 1


@pytest.mark.asyncio
async def test_non_streaming_backend_error_surfaces() -> None:
    """BackendError from the streaming handler is propagated."""
    err = BackendError("boom", status_code=418)

    async def _handle(*_: Any, **__: Any) -> ResponseEnvelope:
        raise err

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={})
    )

    base = create_backend_request_manager(backend_processor=backend_processor)
    cast(Any, base._post_backend_response_coordinator)._streaming_handler.handle = (
        AsyncMock(side_effect=_handle)
    )

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )

    _configure_gate(base)
    with pytest.raises(BackendError) as excinfo:
        await base.process_backend_request(request, "s", _ctx())

    assert excinfo.value.status_code == 418
    assert str(excinfo.value.message) == "boom"


def _make_terminal_error_stream() -> AsyncIterator[ProcessedResponse]:
    payload = (
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"error"}],'
        b'"error":{"status_code":422,"message":"bad"}}\n\n'
    )

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=payload)
        yield ProcessedResponse(content=b"data: [DONE]\n\n")

    return _src()


@pytest.mark.asyncio
async def test_streaming_terminal_error_status_for_dedup() -> None:
    """Terminal error finish_reason maps to the expected dedup completion status."""

    async def _passthrough(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        return stream

    mock_dedup = AsyncMock()
    mock_dedup.check_and_register.return_value = (False, "hashZ")

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_make_terminal_error_stream())
    )

    manager = create_backend_request_manager(
        backend_processor=backend_processor, dedup_service=mock_dedup
    )
    cast(
        Any, manager._post_backend_response_coordinator
    )._streaming_handler.handle = AsyncMock(side_effect=_passthrough)
    _configure_gate(manager)

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="t")],
        stream=True,
    )
    result = await manager.process_backend_request(request, "sess", _ctx())
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    async for _ in result.content:
        pass
    kw = mock_dedup.mark_request_complete.await_args
    assert kw is not None
    assert kw.kwargs.get("status_code") == 422


@pytest.mark.asyncio
async def test_streaming_dedup_marks_complete_after_exhaustion() -> None:
    """Dedup completion only after stream exhaustion with expected arguments."""
    mock_dedup = AsyncMock()
    mock_dedup.check_and_register.return_value = (False, "hash123")

    async def _two_chunk_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"data: chunk1\n\n")
        yield ProcessedResponse(content=b"data: chunk2\n\n")

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_two_chunk_stream())
    )

    base = create_backend_request_manager(
        backend_processor=backend_processor, dedup_service=mock_dedup
    )

    async def _passthrough(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        return stream

    cast(Any, base._post_backend_response_coordinator)._streaming_handler.handle = (
        AsyncMock(side_effect=_passthrough)
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="t")],
        stream=True,
    )

    _configure_gate(base)
    result = await base.process_backend_request(request, "sess", _ctx())
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    mock_dedup.mark_request_complete.assert_not_awaited()
    with contextlib.suppress(StopAsyncIteration):
        while True:
            await result.content.__anext__()
    args = mock_dedup.mark_request_complete.await_args
    assert args is not None


@pytest.mark.asyncio
async def test_empty_stream_recovery_backend_call_count() -> None:
    """Empty-stream retry performs a second backend call and yields retried chunks."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )

    async def empty_stream() -> AsyncIterator[ProcessedResponse]:
        if False:
            yield ProcessedResponse(content="x")

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content='data: {"choices":[{"index":0,"delta":{"content":"."}}]}\n\n'
        )

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=empty_stream()),
        StreamingResponseEnvelope(content=retry_stream()),
    ]

    base = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    session = "sess-parity"

    _configure_gate(base)
    out = await base.process_backend_request(request, session, _ctx())
    n = backend_processor.process_backend_request.await_count

    assert n == 2
    chunks = await _collect_stream(cast(StreamingResponseEnvelope, out))
    assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_swallowed_tool_call_retry_stream() -> None:
    """Swallowed-tool streaming response triggers retry and replacement chunks."""

    def _swallowed_envelope() -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(
            content=_async_iter_from_list(
                [
                    ProcessedResponse(
                        content="dangerous tool response",
                        metadata=_meta(
                            {
                                "tool_call_swallowed": True,
                                "steering_message": "Do not execute that command.",
                                "swallowed_original_content": "rm -rf /",
                                "swallowed_tool_calls": [
                                    {"function": {"name": "shell", "arguments": "{}"}}
                                ],
                            }
                        ),
                    )
                ]
            ),
        )

    def _retry_envelope() -> StreamingResponseEnvelope:
        async def retry_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="safe replacement 1", metadata=_meta({}))
            yield ProcessedResponse(
                content="safe replacement 2", metadata=_meta({"is_done": True})
            )

        return StreamingResponseEnvelope(content=retry_stream())

    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )
    backend_processor.process_backend_request.side_effect = [
        _swallowed_envelope(),
        _retry_envelope(),
    ]
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )
    _configure_gate(manager)
    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    result = await manager.process_backend_request(request, "session-tool", _ctx())
    assert isinstance(result, StreamingResponseEnvelope)
    chunks: list[str] = []
    assert result.content is not None
    async for chunk in result.content:
        chunks.append(str(chunk.content))
    assert any("safe replacement 1" in c for c in chunks)


@pytest.mark.asyncio
async def test_streaming_canonical_usage_metadata_handler_surface() -> None:
    """canonical_usage and handler metadata are forwarded on the streaming envelope."""
    cu = CanonicalUsageRecord(provider_id="openai", model_id="gpt-test")

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"one")

    async def _handle(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(
            content=stream.content,
            status_code=200,
            metadata=_meta({"policy": "ok"}),
            canonical_usage=cu,
        )

    async def _fresh(*_: Any, **__: Any) -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_src())

    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(side_effect=_fresh)
    manager = create_backend_request_manager(backend_processor=backend_processor)
    cast(
        Any, manager._post_backend_response_coordinator
    )._streaming_handler.handle = AsyncMock(side_effect=_handle)
    _configure_gate(manager)
    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    out = await manager.process_backend_request(request, "sess", _ctx())
    assert isinstance(out, StreamingResponseEnvelope)
    assert out.metadata == {"policy": "ok"}
    assert out.canonical_usage == cu


@pytest.mark.asyncio
async def test_tool_retry_marker_skips_second_backend() -> None:
    """Retry-marker short-circuit avoids a second backend invocation."""

    async def _original_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content="proxy replacement",
            metadata=_meta(
                {
                    "tool_call_swallowed": True,
                    "steering_message": "Already handled.",
                }
            ),
        )

    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )
    _configure_gate(manager)
    flagged_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="continue")],
        stream=True,
        extra_body={
            "_tool_call_reactor_retry": True,
            "_tool_call_reactor_retry_count": 1,
        },
    )
    backend_processor.process_backend_request.return_value = (
        StreamingResponseEnvelope(content=_original_stream())
    )
    result = await manager.process_backend_request(
        flagged_request, "session-y", _ctx()
    )
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [c async for c in result.content]
    assert backend_processor.process_backend_request.await_count == 1
    assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_quality_verifier_no_steering_stream() -> None:
    """Quality verifier pass-through leaves content and pending steering unchanged."""
    from src.core.services.quality_verifier_steering_store import (
        PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
    )

    class _DummyAppState:
        def __init__(self, quality_verifier_model: str) -> None:
            self._quality_verifier_model = quality_verifier_model
            self._settings: dict[str, Any] = {}

        def get_setting(self, key: str, default: Any = None) -> Any:
            if key == "app_config":

                class Session:
                    quality_verifier_model = self._quality_verifier_model
                    quality_verifier_frequency = 1

                class Config:
                    session = Session()

                return Config()
            return self._settings.get(key, default)

        def set_setting(self, key: str, value: Any) -> None:
            self._settings[key] = value

        def get_service(self, _t: Any) -> Any:
            return None

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completions(self, request: Any, *_: Any, **__: Any) -> Any:
            self.calls += 1
            return type(
                "R",
                (),
                {"content": "<status>NO_STEERING_NEEDED</status>"},
            )()

    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )
    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, _t: Any) -> Any:
            return backend_service

        def get_service(self, _t: Any) -> Any:
            return None

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=DummyProvider(),
    )
    _configure_gate(manager)

    chunks = [
        ProcessedResponse(content="Hello", metadata={}),
        ProcessedResponse(content=" world", metadata={"is_done": True}),
    ]
    stream_envelope = StreamingResponseEnvelope(content=_async_iter_from_list(chunks))
    backend_processor.process_backend_request.return_value = stream_envelope

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )
    app_state = _DummyAppState("openai:gpt-4o-mini")
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        extensions={
            "quality_verifier_model": "openai:gpt-4o-mini",
            "quality_verifier_frequency": 1,
            "quality_verifier_eligible_turn_count": 2000,
        },
    )
    context.original_request = original_request

    result = await manager.process_backend_request(
        original_request, "session-pass", context
    )
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    forwarded: list[str] = []
    async for chunk in result.content:
        forwarded.append(str(chunk.content))
    await asyncio.sleep(0)
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    text = "".join(forwarded)
    assert "Hello world" in text
    assert pending == {}


@pytest.mark.asyncio
async def test_streaming_request_blocking_backend_envelope_uses_streaming_transport() -> (
    None
):
    """Blocking backend envelope for a streaming client is adapted to SSE transport."""
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"unexpected": True}, status_code=555)
    )

    base = create_backend_request_manager(backend_processor=backend_processor)
    _configure_gate(
        base,
        legacy_streaming_client_blocking_envelope=True,
    )

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    out = await base.process_backend_request(request, "sess", _ctx())
    assert isinstance(out, StreamingResponseEnvelope)
    assert out.status_code == 555


@pytest.mark.asyncio
async def test_migration_diagnostics_only_when_emit_enabled() -> None:
    """Diagnostics keys must not appear unless emit_path_selection_metadata is true."""
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"a": 1})
    )

    base = create_backend_request_manager(backend_processor=backend_processor)

    async def _diag_stream(
        *, stream: StreamingResponseEnvelope, **_: Any
    ) -> StreamingResponseEnvelope:
        async def _chunks() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content={"a": 2})

        return StreamingResponseEnvelope(
            content=_chunks(), media_type="application/json"
        )

    cast(Any, base._post_backend_response_coordinator)._streaming_handler.handle = (
        AsyncMock(side_effect=_diag_stream)
    )

    request = ChatRequest(
        model="openai",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )

    ctx_off = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        extensions={},
    )
    manager = base
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=False,
    )
    await manager.process_backend_request(request, "s", ctx_off)
    assert "migration_stage" not in ctx_off.extensions

    ctx_on = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        extensions={},
    )
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
    )
    await manager.process_backend_request(request, "s", ctx_on)
    assert ctx_on.extensions.get("canonical_path_used") is True
    promo = ctx_on.extensions.get("promotion_guardrails")
    assert isinstance(promo, dict)
    assert promo.get("strict_missing_evidence") is True
    assert promo.get("overall_passed") is False


@pytest.mark.asyncio
async def test_migration_diagnostics_attached_even_when_backend_raises() -> None:
    """Diagnostics must be present on failure paths when emission is enabled."""
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        side_effect=BackendError("backend failed", status_code=503)
    )
    manager = create_backend_request_manager(backend_processor=backend_processor)
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
        connector_stream_first={"openai": True},
    )
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=False,
    )
    ctx = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        backend="openai",
        extensions={},
    )
    with pytest.raises(BackendError):
        await manager.process_backend_request(request, "s", ctx)
    assert ctx.extensions.get("migration_stage") == "canonical_runtime"
    assert ctx.extensions.get("canonical_path_used") is True
    assert ctx.extensions.get("connector_stream_first_used") is True
    assert ctx.extensions.get("forced_backend_stream") is True
    promo = ctx.extensions.get("promotion_guardrails")
    assert isinstance(promo, dict)
    assert promo.get("strict_missing_evidence") is True
    assert promo.get("promotion_blocked") is True
