"""Tests for the AnthropicController request handling logic."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request, Response

from src.anthropic_models import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import AnthropicController


@pytest.mark.asyncio
async def test_controller_preserves_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tool call metadata survives conversion to the domain ChatRequest."""

    processor = SimpleNamespace(process_request=AsyncMock())
    processor.process_request.return_value = object()
    controller = AnthropicController(processor)

    fake_context = object()
    monkeypatch.setattr(
        "src.core.app.controllers.anthropic_controller.fastapi_to_domain_request_context",
        lambda *_args, **_kwargs: fake_context,
    )

    response_payload = {
        "id": "chatcmpl-1",
        "model": "gpt-test",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    fastapi_response = Response(
        content=json.dumps(response_payload),
        media_type="application/json",
    )

    monkeypatch.setattr(
        "src.core.app.controllers.anthropic_controller.domain_response_to_fastapi",
        lambda _resp: fastapi_response,
    )

    app = FastAPI()
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/anthropic/v1/messages",
        "raw_path": b"/anthropic/v1/messages",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)  # type: ignore[arg-type]

    anthropic_request = AnthropicMessagesRequest(
        model="claude-3-sonnet-20240229",
        max_tokens=128,
        messages=[
            AnthropicMessage(
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "weather",
                        "input": {"location": "San Francisco"},
                    }
                ],
            ),
            AnthropicMessage(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": [{"type": "text", "text": "Result text"}],
                    }
                ],
            ),
        ],
    )

    await controller.handle_anthropic_messages(request, anthropic_request)

    assert processor.process_request.await_count == 1
    await_args = processor.process_request.await_args
    chat_request = await_args.args[1]

    assert len(chat_request.messages) == 2

    first_message = chat_request.messages[0]
    assert first_message.role == "assistant"
    assert first_message.tool_calls is not None
    assert first_message.tool_calls[0].id == "call_123"
    assert json.loads(first_message.tool_calls[0].function.arguments) == {
        "location": "San Francisco"
    }

    second_message = chat_request.messages[1]
    assert second_message.role == "tool"
    assert second_message.tool_call_id == "call_123"
    assert second_message.content == "Result text"
