"""Tests for AnthropicController request normalization."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import Request

from src.anthropic_models import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import AnthropicController
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.request_processor_interface import IRequestProcessor


class DummyRequestProcessor(IRequestProcessor):
    """Minimal IRequestProcessor implementation for controller tests."""

    def __init__(self) -> None:
        self.last_request = None
        self.last_context = None

    async def process_request(self, context, request_data):  # type: ignore[override]
        self.last_context = context
        self.last_request = request_data
        return ResponseEnvelope(
            content={
                "choices": [
                    {
                        "message": {"content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            },
            status_code=200,
        )


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/anthropic/v1/messages",
        "query_string": b"",
        "headers": [],
        "client": ("test", 1234),
        "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace(), router=None),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_optional_penalties_remain_none() -> None:
    """AnthropicController should not inject penalty defaults into ChatRequest."""

    processor = DummyRequestProcessor()
    controller = AnthropicController(processor)
    request = _build_request()

    payload = AnthropicMessagesRequest(
        model="claude-3-sonnet-20240229",
        messages=[AnthropicMessage(role="user", content="Hello")],
    )

    response = asyncio.run(controller.handle_anthropic_messages(request, payload))

    assert processor.last_request is not None
    chat_request = processor.last_request

    assert chat_request.frequency_penalty is None
    assert chat_request.presence_penalty is None

    assert response.status_code == 200
    assert b"Hello" not in response.body  # response uses dummy payload
