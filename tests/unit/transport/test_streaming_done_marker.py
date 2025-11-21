"""Regression tests for streaming completion markers.

Ensure streaming responses always emit a final `[DONE]` marker even when
providers omit it, and never duplicate the marker when it is already present.
"""

from __future__ import annotations

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
