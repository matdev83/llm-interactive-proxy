"""Regression tests for streaming completion markers.

Ensure streaming responses always emit a final `[DONE]` marker even when
providers omit it, and never duplicate the marker when it is already present.
"""

from __future__ import annotations

import json

import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_service import BackendService
from src.core.transport.fastapi.response_adapters import (
    to_fastapi_streaming_response,
)


@pytest.mark.asyncio
async def test_streaming_response_appends_done_when_missing() -> None:
    async def _generator():
        yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

    envelope = StreamingResponseEnvelope(content=_generator())
    response = to_fastapi_streaming_response(envelope)

    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks[-1] == b"data: [DONE]\n\n"
    assert len(chunks) == 2  # one data chunk + one final [DONE]


@pytest.mark.asyncio
async def test_streaming_response_does_not_duplicate_done() -> None:
    async def _generator():
        yield ProcessedResponse(content="data: [DONE]\n\n")

    envelope = StreamingResponseEnvelope(content=_generator())
    response = to_fastapi_streaming_response(envelope)

    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [b"data: [DONE]\n\n"]


@pytest.mark.asyncio
async def test_wire_capture_adapter_appends_done_when_missing() -> None:
    async def _generator():
        yield ProcessedResponse(content={"choices": [{"delta": {"content": "hi"}}]})

    stream = BackendService._stream_as_sse_bytes(_generator())
    chunks = [chunk async for chunk in stream]

    assert chunks[-1] == b"data: [DONE]\n\n"
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_wire_capture_adapter_respects_existing_done() -> None:
    async def _generator():
        yield ProcessedResponse(content="data: [DONE]\n\n")

    stream = BackendService._stream_as_sse_bytes(_generator())
    chunks = [chunk async for chunk in stream]

    assert chunks == [b"data: [DONE]\n\n"]


@pytest.mark.asyncio
async def test_streaming_response_preserves_error_chunk() -> None:
    error_payload = {
        "id": "chatcmpl-error-test",
        "object": "chat.completion.chunk",
        "created": 123,
        "model": "unit-test-model",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
        "error": {"message": "boom", "type": "api_error", "code": 404},
    }

    async def _generator():
        yield ProcessedResponse(content=error_payload)

    envelope = StreamingResponseEnvelope(content=_generator())
    response = to_fastapi_streaming_response(envelope)

    chunks = [chunk.decode("utf-8") async for chunk in response.body_iterator]

    assert chunks[0].startswith("data: {")
    assert '"finish_reason": "error"' in chunks[0]
    assert '"message": "boom"' in chunks[0]
    assert "data: [DONE]" in chunks[-1]


@pytest.mark.asyncio
async def test_wire_capture_formats_plain_string_chunk() -> None:
    error_chunk = json.dumps(
        {
            "id": "chatcmpl-error-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "unit-test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {"message": "boom", "type": "api_error", "code": 404},
        }
    )

    async def _generator():
        yield ProcessedResponse(content=error_chunk)

    stream = BackendService._stream_as_sse_bytes(_generator())
    chunks = [chunk.decode("utf-8") async for chunk in stream]

    assert chunks[0] == f"data: {error_chunk}\n\n"
    assert chunks[-1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_wire_capture_normalizes_bracket_done_marker() -> None:
    async def _generator():
        yield ProcessedResponse(content='["DONE"]')

    stream = BackendService._stream_as_sse_bytes(_generator())
    chunks = [chunk.decode("utf-8") async for chunk in stream]

    assert chunks == ["data: [DONE]\n\n"]
