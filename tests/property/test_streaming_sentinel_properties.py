from __future__ import annotations

import pytest
from hypothesis import given
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import SentinelManager, StreamingContent
from src.core.ports.streaming_metrics import reset_metrics
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import (
    chunk_stream_strategy,
    chunk_stream_with_done_strategy,
)
from tests.utils.property_test_helpers import async_iter, async_list


@pytest.mark.asyncio
@given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=5))
@property_test_settings()
async def test_property_2_single_sentinel_emission_with_done(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 2: Single sentinel emission (stream already emits done marker).

    SSEAssembler must emit exactly one [DONE] sentinel and only after data chunks.
    """

    reset_metrics()
    assembler = SSEAssembler()
    stream = async_iter(chunks)
    outputs = await async_list(assembler.assemble_stream(stream))
    sentinel = SentinelManager.format_sse_done()
    sentinel_hits = [payload.count(sentinel) for payload in outputs]
    assert sum(sentinel_hits) == 1
    assert sentinel_hits[-1] == 1


@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy(min_size=1, max_size=5))
@property_test_settings()
async def test_property_2_single_sentinel_emission_without_done(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 2: Single sentinel emission (missing done marker).

    Even when upstream never yields a done chunk, SSEAssembler must append
    exactly one [DONE] sentinel.
    """

    for chunk in chunks:
        chunk.is_done = False
        chunk.metadata.pop("finish_reason", None)

    reset_metrics()
    assembler = SSEAssembler()
    stream = async_iter(chunks)
    outputs = await async_list(assembler.assemble_stream(stream))
    sentinel = SentinelManager.format_sse_done()
    sentinel_hits = [payload.count(sentinel) for payload in outputs]
    assert sum(sentinel_hits) == 1
    assert sentinel_hits[-1] == 1


def test_property_14_and_15_sentinel_consistency() -> None:
    """
    Properties 14 & 15: Sentinel utility usage and format consistency.

    The sentinel chunk created via SentinelManager must serialize to the same
    SSE bytes regardless of optional metadata.
    """

    default_chunk = SentinelManager.create_done_chunk()
    default_bytes = default_chunk.to_bytes()
    assert default_bytes == SentinelManager.format_sse_done()

    provider_chunk = SentinelManager.create_done_chunk()
    provider_chunk.metadata["provider"] = "any-backend"
    assert provider_chunk.to_bytes() == default_bytes


@pytest.mark.asyncio
@given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=3))
@property_test_settings()
async def test_property_16_hybrid_sentinel_after_reasoning(
    chunks: list[StreamingContent],
) -> None:
    """
    Property 16: Hybrid sentinel coordination.

    Sentinels must be emitted only after reasoning/content phases complete.
    """

    if chunks:
        chunks[0].metadata["reasoning_content"] = "internal-thought"

    reset_metrics()
    assembler = SSEAssembler()
    outputs = await async_list(assembler.assemble_stream(async_iter(chunks)))
    sentinel = SentinelManager.format_sse_done()
    sentinel_hits = [payload.count(sentinel) for payload in outputs]
    assert sum(sentinel_hits) >= 1
    assert sentinel_hits[-1] >= 1
