"""Regression tests for coalesced SSE frame handling in BackendCompletionFlow."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _build_flow_with_mocks() -> dict[str, Any]:
    deps: dict[str, Any] = {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "connector_invoker": MagicMock(),
    }
    deps["wire_capture_orchestrator"].detect_key_name.return_value = "test-key"
    deps["wire_capture_orchestrator"].wrap_inbound_stream.side_effect = (
        lambda **kwargs: kwargs["stream"]
    )
    deps["flow"] = BackendCompletionFlow(**deps)
    return deps


async def _empty_processed_stream() -> AsyncIterator[ProcessedResponse]:
    if False:
        yield ProcessedResponse(content=b"")


@pytest.mark.asyncio
async def test_streaming_response_splits_coalesced_lf_frames() -> None:
    deps = _build_flow_with_mocks()
    flow: BackendCompletionFlow = deps["flow"]

    async def _coalesced_bytes() -> AsyncIterator[bytes]:
        yield (
            b'data: {"id":"a1","model":"kimi-for-coding","created":1,'
            b'"choices":[{"delta":{"content":"A"}}]}\n\n'
            b'data: {"id":"a1","model":"kimi-for-coding","created":1,'
            b'"choices":[{"delta":{"content":"B"}}]}\n\n'
            b"data: [DONE]\n\n"
        )

    deps["stream_formatting_service"].stream_as_sse_bytes.return_value = (
        _coalesced_bytes()
    )

    captured: list[ProcessedResponse] = []

    async def _capture_and_return(**kwargs: Any) -> StreamingResponseEnvelope:
        streaming_result: StreamingResponseEnvelope = kwargs["result"]
        assert streaming_result.content is not None
        async for chunk in streaming_result.content:
            captured.append(chunk)
        return streaming_result

    deps["usage_accounting_orchestrator"].handle_streaming_response = AsyncMock(
        side_effect=_capture_and_return
    )

    await flow._handle_streaming_response(
        result=StreamingResponseEnvelope(content=_empty_processed_stream()),
        backend_type="kimi-code",
        effective_model="kimi/kimi-for-coding",
        context=None,
        domain_request=CanonicalChatRequest(
            model="kimi-code:kimi/kimi-for-coding",
            messages=[ChatMessage(role="user", content="test")],
        ),
        session_id_for_backend=None,
        session_key=None,
    )

    decoded = [
        chunk.content.decode("utf-8", errors="replace")
        for chunk in captured
        if isinstance(chunk.content, bytes)
    ]

    assert len(decoded) == 3
    assert decoded[0].count("data:") == 1
    assert decoded[1].count("data:") == 1
    assert decoded[2].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_streaming_response_splits_coalesced_crlf_frames() -> None:
    deps = _build_flow_with_mocks()
    flow: BackendCompletionFlow = deps["flow"]

    async def _coalesced_bytes_crlf() -> AsyncIterator[bytes]:
        yield (
            b'data: {"id":"b2","model":"openrouter/test","created":2,'
            b'"choices":[{"delta":{"content":"X"}}]}\r\n\r\n'
            b'data: {"id":"b2","model":"openrouter/test","created":2,'
            b'"choices":[{"delta":{"content":"Y"}}]}\r\n\r\n'
        )

    deps["stream_formatting_service"].stream_as_sse_bytes.return_value = (
        _coalesced_bytes_crlf()
    )

    captured: list[ProcessedResponse] = []

    async def _capture_and_return(**kwargs: Any) -> StreamingResponseEnvelope:
        streaming_result: StreamingResponseEnvelope = kwargs["result"]
        assert streaming_result.content is not None
        async for chunk in streaming_result.content:
            captured.append(chunk)
        return streaming_result

    deps["usage_accounting_orchestrator"].handle_streaming_response = AsyncMock(
        side_effect=_capture_and_return
    )

    await flow._handle_streaming_response(
        result=StreamingResponseEnvelope(content=_empty_processed_stream()),
        backend_type="openrouter",
        effective_model="openrouter/test",
        context=None,
        domain_request=CanonicalChatRequest(
            model="openrouter:test/model",
            messages=[ChatMessage(role="user", content="test")],
        ),
        session_id_for_backend=None,
        session_key=None,
    )

    decoded = [
        chunk.content.decode("utf-8", errors="replace")
        for chunk in captured
        if isinstance(chunk.content, bytes)
    ]

    assert len(decoded) == 2
    assert all(frame.count("data:") == 1 for frame in decoded)
    assert any('"content":"X"' in frame for frame in decoded)
    assert any('"content":"Y"' in frame for frame in decoded)
