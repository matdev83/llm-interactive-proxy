"""Focused tests for empty SSE body iterator (null envelope content)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.transport.fastapi.adapters.response.streaming_response_builder import (
    StreamingResponseBuilder,
)
from starlette.responses import StreamingResponse


@pytest.mark.asyncio
async def test_build_null_content_no_chunks_and_first_anext_stops() -> None:
    """Null envelope content must yield zero bytes before StopAsyncIteration."""

    builder = StreamingResponseBuilder()
    envelope = StreamingResponseEnvelope(
        content=None,
        headers={},
        media_type="text/event-stream",
    )
    response = builder.build(envelope)
    assert isinstance(response, StreamingResponse)

    n_chunks = 0
    async for _ in response.body_iterator:
        n_chunks += 1
    assert n_chunks == 0

    response_fresh = builder.build(envelope)
    body_it = cast(AsyncIterator[bytes], response_fresh.body_iterator)
    with pytest.raises(StopAsyncIteration):
        await body_it.__anext__()
