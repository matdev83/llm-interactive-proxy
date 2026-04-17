"""Regression tests for streaming usage protocol shapes.

These tests protect two distinct protocols:

1. Legacy Chat Completions SSE:
   usage must be emitted as a separate final chunk with ``choices: []``
   before the terminal ``[DONE]`` marker.

2. Responses API SSE:
   usage must be nested under ``response.completed.response.usage``.

The regression being guarded here is subtle but critical: attaching legacy
``usage`` to a normal assistant chunk can cause OpenAI-compatible clients to
interpret that chunk as terminal and close the connection immediately.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response


class _NeverDisconnectRequest:
    """Minimal request stub for controller streaming tests."""

    def __init__(self) -> None:
        self.state = SimpleNamespace()

    async def is_disconnected(self) -> bool:
        return False


def _decode_sse_json_events(parts: list[str]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for part in parts:
        if not part.startswith("data: "):
            continue
        payload = part[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        events.append(json.loads(payload))
    return events


def _chunk_to_bytes(chunk: str | bytes | memoryview) -> bytes:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, memoryview):
        return chunk.tobytes()
    return chunk.encode("utf-8")


@pytest.mark.asyncio
async def test_legacy_chat_completions_usage_is_split_into_final_empty_choices_chunk() -> (
    None
):
    """Legacy clients must receive usage in the documented final chunk shape."""

    async def _stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={
                "id": "chatcmpl-usage-regression",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            }
        )

    envelope = StreamingResponseEnvelope(
        content=_stream(),
        media_type="text/event-stream",
    )

    response = to_fastapi_streaming_response(envelope)
    raw_chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]

    assert raw_chunks[-1] == b"data: [DONE]\n\n"

    payloads = []
    for raw_chunk in raw_chunks[:-1]:
        chunk = _chunk_to_bytes(raw_chunk)
        if not chunk.startswith(b"data: "):
            continue
        payloads.append(json.loads(chunk.decode("utf-8").strip()[6:]))
    assert len(payloads) == 2

    content_chunk, usage_chunk = payloads

    assert content_chunk["choices"][0]["delta"]["content"] == "Hello"
    assert "usage" not in content_chunk

    assert usage_chunk["id"] == "chatcmpl-usage-regression"
    assert usage_chunk["object"] == "chat.completion.chunk"
    assert usage_chunk["choices"] == []
    assert usage_chunk["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_responses_api_usage_stays_nested_under_response_completed_event() -> (
    None
):
    """Responses clients must receive usage on the completed response object."""

    async def _responses_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={
                "id": "resp_usage_regression",
                "object": "response.chunk",
                "created": 123,
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 2,
                    "total_tokens": 7,
                },
            }
        )

    controller = ResponsesController(
        request_processor=MagicMock(),
        translation_service=MagicMock(),
    )
    envelope = StreamingResponseEnvelope(content=_responses_stream())
    request = _NeverDisconnectRequest()
    domain_request = ChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    stream = controller._stream_response_envelope(
        request=cast(Request, request),
        domain_request=domain_request,
        response=envelope,
        request_id="req-usage-regression",
    )

    parts: list[str] = []
    while True:
        try:
            parts.append(await stream.__anext__())
        except StopAsyncIteration:
            break

    events = _decode_sse_json_events(parts)
    assert events

    completed = next(
        event for event in events if event.get("type") == "response.completed"
    )
    response_payload = completed["response"]
    assert isinstance(response_payload, dict)
    assert response_payload["usage"] == {
        "input_tokens": 5,
        "output_tokens": 2,
        "total_tokens": 7,
    }
    assert "usage" not in completed
