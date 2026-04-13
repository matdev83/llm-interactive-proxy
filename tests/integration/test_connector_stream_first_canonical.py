"""Integration: connector stream-first cohort under canonical gate (Wave 6 / 8.1 framework)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.migration_gate_service import MigrationGateService

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
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
        connector_stream_first={"openai": True},
    )

    streaming = cast(
        Any, cast(Any, manager._post_backend_response_coordinator)._streaming_handler
    )
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
    assert ctx.extensions.get("connector_stream_first_used") is True
    assert ctx.extensions.get("forced_backend_stream") is True


@pytest.mark.asyncio
async def test_explicit_cohort_false_skips_streaming_handler_for_native_stream() -> (
    None
):
    """Cohort ``False`` keeps ``stream=False`` at the backend; RAW passthrough adapts down."""

    async def _src() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"choices": [{"message": {"content": "down"}}]})

    backend_processor = MagicMock()

    async def _proc(*, request: ChatRequest, **__: Any) -> StreamingResponseEnvelope:
        assert request.stream is False
        return StreamingResponseEnvelope(content=_src())

    backend_processor.process_backend_request = AsyncMock(side_effect=_proc)

    manager = create_backend_request_manager(backend_processor=backend_processor)
    streaming = cast(
        Any, cast(Any, manager._post_backend_response_coordinator)._streaming_handler
    )
    streaming.handle = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_src(), status_code=200)
    )

    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
        connector_stream_first={"openai": False},
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
    streaming.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_canonical_does_not_force_backend_stream_when_cohort_not_opted_in() -> (
    None
):
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    manager = create_backend_request_manager(backend_processor=backend_processor)

    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
        connector_stream_first={},
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
    await manager.process_backend_request(request, "sess", ctx)
    called = backend_processor.process_backend_request.await_args
    assert called is not None
    assert called.kwargs["request"].stream is False


@pytest.mark.asyncio
async def test_cohort_enabled_handles_blocking_backend_without_native_streaming() -> (
    None
):
    """Connector adaptation: cohort can stay enabled even if backend returns blocking envelope."""
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": "blocking"})
    )

    manager = create_backend_request_manager(backend_processor=backend_processor)

    async def _stream_passthrough(
        *, stream: StreamingResponseEnvelope, **__: Any
    ) -> StreamingResponseEnvelope:
        return stream

    cast(
        Any, cast(Any, manager._post_backend_response_coordinator)._streaming_handler
    ).handle = AsyncMock(side_effect=_stream_passthrough)

    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=True,
        emit_path_selection_metadata=True,
        connector_stream_first={"openai": True},
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
    assert out.content == {"ok": "blocking"}
    cast(
        Any, cast(Any, manager._post_backend_response_coordinator)._streaming_handler
    ).handle.assert_awaited_once()
    assert ctx.extensions.get("connector_stream_first_used") is True
    assert ctx.extensions.get("forced_backend_stream") is True
