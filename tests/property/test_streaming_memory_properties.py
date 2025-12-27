from __future__ import annotations

import pytest
from hypothesis import given
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import chunk_stream_with_done_strategy


@pytest.mark.asyncio
@given(chunks=chunk_stream_with_done_strategy(min_size=5, max_size=30))
@property_test_settings(max_examples=15)
async def test_property_26_constant_memory_usage(chunks) -> None:
    """
    Property 26: Constant memory usage.

    ContentAccumulationProcessor must respect its max_buffer_bytes cap regardless
    of stream length.
    """

    max_buffer = 1024
    registry = StreamingContextRegistry()
    processor = ContentAccumulationProcessor(
        max_buffer_bytes=max_buffer, registry=registry
    )
    stream_id = "property-26-stream"

    for chunk in chunks:
        chunk.stream_id = stream_id
        chunk.metadata["stream_id"] = stream_id
        await processor.process(chunk)
        state = registry.get_content_state(stream_id)
        assert (
            state.byte_length <= max_buffer
        ), "Processor exceeded configured buffer cap"
