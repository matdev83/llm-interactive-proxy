from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _FakeRequest:
    """Minimal request stub for testing streaming cancellation handling."""

    def __init__(self, disconnect_sequence: list[bool]) -> None:
        self._disconnect_iter = iter(disconnect_sequence)
        self.state = SimpleNamespace()

    async def is_disconnected(self) -> bool:
        try:
            return next(self._disconnect_iter)
        except StopIteration:
            return False


async def _make_stream() -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(
        content={
            "id": "resp_123",
            "object": "response.chunk",
            "created": 123,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "hello"},
                    "finish_reason": None,
                }
            ],
        },
    )
    yield ProcessedResponse(
        content={
            "id": "resp_123",
            "object": "response.chunk",
            "created": 123,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "world"},
                    "finish_reason": "stop",
                }
            ],
        },
    )


async def _make_tool_stream() -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(
        content="",
        metadata={
            "id": "resp_tool",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "fetch_data",
                        "arguments": '{"query":"status"}',
                    },
                }
            ],
        },
    )
    yield ProcessedResponse(content="", metadata={"id": "resp_tool", "is_done": True})


def _decode_sse_payloads(blob: str) -> list[dict]:
    payloads: list[dict] = []
    for line in blob.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            continue
        payloads.append(json.loads(raw))
    return payloads


@pytest.mark.asyncio
async def test_streaming_disconnect_triggers_backend_cancel() -> None:
    controller = ResponsesController(
        request_processor=MagicMock(),
        translation_service=MagicMock(),
    )

    cancel_called = asyncio.Event()

    async def _cancel_callback() -> None:
        cancel_called.set()

    envelope = StreamingResponseEnvelope(
        content=_make_stream(),
        cancel_callback=_cancel_callback,
    )

    request = _FakeRequest(disconnect_sequence=[False, True])
    domain_request = ChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    stream = controller._stream_response_envelope(
        request=request,
        domain_request=domain_request,
        response=envelope,
        request_id="req-test",
    )

    parts: list[str] = []
    while True:
        try:
            parts.append(await stream.__anext__())
        except StopAsyncIteration:
            break
    blob = "".join(parts)
    assert "hello" in blob
    assert "response.output_text.delta" in blob
    assert "response.chunk" not in blob

    await asyncio.wait_for(cancel_called.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_streaming_tool_calls_emit_wire_events_only() -> None:
    controller = ResponsesController(
        request_processor=MagicMock(),
        translation_service=MagicMock(),
    )

    envelope = StreamingResponseEnvelope(content=_make_tool_stream())
    request = _FakeRequest(disconnect_sequence=[False, False, False])
    domain_request = ChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="tool")],
        stream=True,
    )

    stream = controller._stream_response_envelope(
        request=request,
        domain_request=domain_request,
        response=envelope,
        request_id="req-tool",
    )

    parts: list[str] = []
    while True:
        try:
            parts.append(await stream.__anext__())
        except StopAsyncIteration:
            break
    payloads = _decode_sse_payloads("".join(parts))
    assert payloads
    assert all(payload.get("object") != "response.chunk" for payload in payloads)
    types = [payload.get("type") for payload in payloads]
    assert "response.function_call_arguments.delta" in types
    assert "response.function_call_arguments.done" in types
    assert "response.output_item.done" in types
    assert types[-1] == "response.completed"
