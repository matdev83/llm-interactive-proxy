"""Tests for AnthropicController streaming conversions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from src.anthropic_converters import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import AnthropicController
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


async def _empty_receive() -> dict[str, bytes | bool]:
    return {"type": "http.request", "body": b"", "more_body": False}


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/anthropic/v1/messages",
        "headers": [],
        "query_string": b"",
        "client": ("test", 1234),
        "root_path": "",
        "scheme": "http",
        "server": ("test", 80),
        "app": MagicMock(state=SimpleNamespace(service_provider=MagicMock())),
    }
    return Request(scope, _empty_receive)


async def _streaming_chunks() -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(
        content=(
            'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
            '"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        ),
        metadata={"id": "chatcmpl-1", "model": "gpt-4o"},
    )
    yield ProcessedResponse(
        content=(
            'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", '
            '"choices": [{"finish_reason": "stop"}]}\n\n'
        ),
        metadata={"id": "chatcmpl-1", "model": "gpt-4o"},
    )
    yield ProcessedResponse(
        content="data: [DONE]\n\n",
        metadata={"id": "chatcmpl-1", "model": "gpt-4o"},
    )


@pytest.mark.asyncio
async def test_streaming_chunks_translated_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    request_processor = AsyncMock()
    request_processor.process_request.return_value = StreamingResponseEnvelope(
        content=_streaming_chunks(),
        headers={"content-type": "text/event-stream"},
    )

    controller = AnthropicController(request_processor)

    dummy_context = SimpleNamespace(domain_request=None, processing_context={})
    monkeypatch.setattr(
        "src.core.transport.fastapi.request_adapters.fastapi_to_domain_request_context",
        lambda request, attach_original=True: dummy_context,
    )

    request = _build_request()
    anthropic_request = AnthropicMessagesRequest(
        model="claude-3-sonnet-20240229",
        messages=[AnthropicMessage(role="user", content="Hello")],
        stream=True,
    )

    response = await controller.handle_anthropic_messages(request, anthropic_request)

    assert response.media_type == "text/event-stream; charset=utf-8"

    chunks: list[str] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk.decode("utf-8"))

    assert any("event: content_block_delta" in chunk for chunk in chunks)
    assert any("event: message_delta" in chunk or "event: message_stop" in chunk for chunk in chunks)
