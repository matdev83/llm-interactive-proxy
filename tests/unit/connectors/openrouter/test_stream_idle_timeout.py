from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from src.connectors.openrouter import OpenRouterBackend
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.mark.asyncio
async def test_openrouter_stream_idle_timeout_emits_keepalive_and_error() -> None:
    backend = OpenRouterBackend(
        client=MagicMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )

    async def _silent_stream() -> AsyncIterator[ProcessedResponse]:
        await asyncio.Event().wait()
        if False:  # pragma: no cover
            yield ProcessedResponse(content="")

    wrapped = backend._wrap_stream_with_idle_timeout(
        _silent_stream(),
        stream_id="session-1",
        model_name="openrouter:test-model",
        keepalive_interval=0.01,
        idle_timeout=0.03,
        cancel_callback=None,
    )

    chunks: list[ProcessedResponse] = []

    async def _consume() -> None:
        async for chunk in wrapped:
            chunks.append(chunk)
            if chunk.metadata and chunk.metadata.get("finish_reason") == "error":
                break

    await asyncio.wait_for(_consume(), timeout=1.0)

    assert any(chunk.metadata and chunk.metadata.get("_keepalive") for chunk in chunks)
    assert any(
        chunk.metadata and chunk.metadata.get("finish_reason") == "error"
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_openrouter_stream_idle_timeout_passes_through_fast_chunk() -> None:
    backend = OpenRouterBackend(
        client=MagicMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )

    async def _fast_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content='data: {"choices": []}\n\n')

    wrapped = backend._wrap_stream_with_idle_timeout(
        _fast_stream(),
        stream_id="session-2",
        model_name="openrouter:test-model",
        keepalive_interval=0.05,
        idle_timeout=0.2,
        cancel_callback=None,
    )

    chunks = [chunk async for chunk in wrapped]

    assert len(chunks) == 1
    assert chunks[0].metadata is None or "_keepalive" not in chunks[0].metadata
