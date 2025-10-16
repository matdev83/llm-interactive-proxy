from __future__ import annotations

import asyncio
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

    first_chunk = await stream.__anext__()
    assert "hello" in first_chunk

    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()

    await asyncio.wait_for(cancel_called.wait(), timeout=0.1)
