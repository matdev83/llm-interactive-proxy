from __future__ import annotations

import pytest
from hypothesis import given
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_metrics import get_metrics_instance, reset_metrics
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import chunk_stream_with_done_strategy
from tests.utils.property_test_helpers import async_iter, async_list


@pytest.mark.asyncio
@given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=6))
@property_test_settings()
async def test_property_13_metrics_emission(
    chunks: list,
) -> None:
    """
    Property 13: Metrics emission.

    Completing a stream must increment chunk and sentinel metrics exactly once.
    """

    reset_metrics()
    assembler = SSEAssembler()
    await async_list(assembler.assemble_stream(async_iter(chunks)))

    metrics = get_metrics_instance().get_global_metrics()
    expected_chunks = sum(
        1 for chunk in chunks if not chunk.is_done and not chunk.is_empty
    )
    assert metrics["chunks_sent"] >= expected_chunks
    assert metrics["sentinels_emitted"] >= 1
