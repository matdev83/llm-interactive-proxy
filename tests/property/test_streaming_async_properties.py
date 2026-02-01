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


@pytest.mark.slow
@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy(min_size=2, max_size=8))
@property_test_settings()
async def test_property_27_incremental_middleware_processing(
    chunks,
) -> None:
    """
    Property 27: Incremental middleware processing.

    StreamNormalizer must emit a chunk for every non-empty input chunk without buffering.
    Empty chunks are filtered out by the normalizer.
    """

    # Ensure only the last chunk is marked as done to mimic pipeline behavior.
    for chunk in chunks[:-1]:
        chunk.is_done = False
        chunk.metadata.pop("finish_reason", None)
    chunks[-1].is_done = True
    chunks[-1].metadata["finish_reason"] = chunks[-1].metadata.get(
        "finish_reason", "stop"
    )

    # Ensure chunks have non-empty content so they are not filtered out
    # Empty chunks without is_done=True are skipped by StreamNormalizer
    # Note: whitespace-only content is also considered empty (content.strip() == "")
    for i, chunk in enumerate(chunks):
        # Use actual non-whitespace content to ensure chunk is not filtered
        needs_content = not chunk.is_done and (
            not chunk.content
            or (isinstance(chunk.content, str) and not chunk.content.strip())
        )
        if needs_content:
            # Create new chunk with updated content to force is_empty recomputation
            chunk = StreamingContent(
                content=f"chunk_{i}",
                metadata=chunk.metadata,
                is_done=chunk.is_done,
                is_empty=None,  # Force recomputation
                stream_id=chunk.stream_id,
                is_cancellation=chunk.is_cancellation,
                usage=chunk.usage,
                raw_data=chunk.raw_data,
            )
            chunks[i] = chunk

    normalizer = StreamNormalizer([_PassthroughProcessor()])
    stream = async_iter(chunks)
    outputs = [
        chunk
        async for chunk in normalizer.process_stream(stream, output_format="objects")
    ]

    # Non-empty chunks (with non-whitespace content) plus the final done marker should all be emitted
    # A chunk is considered non-empty if it has content that is not just whitespace
    def is_non_empty(c: StreamingContent) -> bool:
        if c.is_done:
            return True
        if not c.content:
            return False
        if isinstance(c.content, str):
            return bool(c.content.strip())
        return True

    non_empty_or_done = [c for c in chunks if is_non_empty(c)]
    assert len(outputs) == len(non_empty_or_done)


@pytest.mark.asyncio
async def test_property_28_event_loop_yielding() -> None:
    """
    Property 28: Event loop yielding.

    SSEAssembler must yield control to the event loop between chunk emissions.
    """

    # Set yield_interval=1 to ensure yielding on every chunk for testing
    assembler = SSEAssembler(yield_interval=1)
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

    # Assembler yields control for non-done chunks only (see SSEAssembler.assemble_stream line 299)
    non_done_chunks = [c for c in chunks if not c.is_done]
    assert yielded_calls >= len(
        non_done_chunks
    ), f"Assembler failed to yield control per non-done chunk (expected >= {len(non_done_chunks)}, got {yielded_calls})"
