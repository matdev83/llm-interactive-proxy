"""Tests for ``wrap_processed_stream_with_idle_keepalive``."""

from __future__ import annotations

import asyncio

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.streaming.processed_stream_idle_keepalive import (
    wrap_processed_stream_with_idle_keepalive,
)


@pytest.mark.asyncio
async def test_wrap_emits_keepalive_between_slow_chunks() -> None:
    async def slow_stream() -> asyncio.AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content=b"first", metadata={})
        await asyncio.sleep(0.15)
        yield ProcessedResponse(content=b"second", metadata={})

    chunks: list[ProcessedResponse] = []
    async for chunk in wrap_processed_stream_with_idle_keepalive(
        slow_stream(),
        keepalive_interval=0.05,
        idle_timeout=None,
        stream_id="s1",
        model_name="m",
    ):
        chunks.append(chunk)

    assert any(
        isinstance(c.metadata, dict) and c.metadata.get("_keepalive") for c in chunks
    )
    assert chunks[0].content == b"first"
    assert chunks[-1].content == b"second"
