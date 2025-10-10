"""Tests for AnthropicController streaming conversions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from src.anthropic_converters import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import AnthropicController
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _StreamingProcessor(IRequestProcessor):
    """Return a streaming response that emits OpenAI-formatted SSE chunks."""

    async def process_request(
        self,
        context: Any,
        request_data: Any,
    ) -> StreamingResponseEnvelope:
        async def _stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content='data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
            )
            yield ProcessedResponse(
                content='data: {"choices": [{"delta": {"content": [{"type": "text", "text": "Hello"}]}}]}\n\n'
            )
            yield ProcessedResponse(
                content='data: {"choices": [{"finish_reason": "stop"}]}\n\n'
            )
            yield ProcessedResponse(content='data: [DONE]\n\n')

        return StreamingResponseEnvelope(content=_stream())


@pytest.mark.asyncio
async def test_streaming_response_converted_to_anthropic() -> None:
    """Ensure streaming responses are converted to Anthropic SSE format."""

    controller = AnthropicController(_StreamingProcessor())

    app = FastAPI()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    anthropic_request = AnthropicMessagesRequest(
        model="claude-3-sonnet-20240229",
        messages=[AnthropicMessage(role="user", content="Hi")],
        stream=True,
    )

    response = await controller.handle_anthropic_messages(request, anthropic_request)

    assert isinstance(response, StreamingResponse)
    chunks: list[str] = []
    async for chunk in response.body_iterator:  # type: ignore[assignment]
        chunks.append(chunk.decode("utf-8"))

    assert len(chunks) == 4

    prefix = "data: "
    first_payload = json.loads(chunks[0][len(prefix) :])
    assert first_payload["type"] == "message_start"
    assert first_payload["message"] == {"role": "assistant"}

    second_payload = json.loads(chunks[1][len(prefix) :])
    assert second_payload["type"] == "content_block_delta"
    assert second_payload["delta"]["text"] == "Hello"

    third_payload = json.loads(chunks[2][len(prefix) :])
    assert third_payload["type"] == "message_delta"
    assert third_payload["delta"]["stop_reason"] == "end_turn"

    assert chunks[3] == "data: [DONE]\n\n"
