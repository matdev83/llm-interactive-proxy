from __future__ import annotations

import asyncio

import pytest
from hypothesis import given
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import chunk_stream_strategy
from tests.utils.property_test_helpers import async_iter, async_list


class _PassthroughProcessor(IStreamProcessor):
    async def process(self, content: StreamingContent) -> StreamingContent:
        return content

    def reset(self) -> None:
        return None


@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy(min_size=2, max_size=8))
@property_test_settings()
async def test_property_27_incremental_middleware_processing(
    chunks,
) -> None:
    """
    Property 27: Incremental middleware processing.

    StreamNormalizer must emit a chunk for every input chunk without buffering.
    """

    # Ensure only the last chunk is marked as done to mimic pipeline behavior.
    for chunk in chunks[:-1]:
        chunk.is_done = False
        chunk.metadata.pop("finish_reason", None)
    chunks[-1].is_done = True
    chunks[-1].metadata["finish_reason"] = chunks[-1].metadata.get(
        "finish_reason", "stop"
    )

    normalizer = StreamNormalizer([_PassthroughProcessor()])
    stream = async_iter(chunks)
    outputs = [
        chunk
        async for chunk in normalizer.process_stream(stream, output_format="objects")
    ]
    assert len(outputs) == len(chunks)


@pytest.mark.asyncio
async def test_property_28_event_loop_yielding() -> None:
    """
    Property 28: Event loop yielding.

    SSEAssembler must yield control to the event loop between chunk emissions.
    """

    assembler = SSEAssembler()
    chunks = [
        StreamingContent(
            content="first",
            metadata={"provider": "test", "stream_id": "yield-stream"},
            is_done=False,
        ),
        StreamingContent(
            content="",
            metadata={
                "provider": "test",
                "stream_id": "yield-stream",
                "finish_reason": "stop",
            },
            is_done=True,
        ),
    ]

    original_sleep = asyncio.sleep
    yielded_calls = 0

    async def tracking_sleep(delay: float, result=None):
        nonlocal yielded_calls
        if delay == 0:
            yielded_calls += 1
        return await original_sleep(delay, result)

    asyncio.sleep = tracking_sleep  # type: ignore[assignment]
    try:
        await async_list(assembler.assemble_stream(async_iter(chunks)))
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert yielded_calls >= len(chunks), "Assembler failed to yield control per chunk"
