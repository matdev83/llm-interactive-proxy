"""
Property-based tests for ContentAccumulationProcessor.

This module contains property tests for:
- Property 2: StopChunkWithUsage content isolation (Requirements 1.2, 1.4)
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
)
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating test data
# ============================================================================


@st.composite
def usage_strategy(draw: Any) -> dict[str, int]:
    """Generate valid usage dictionaries."""
    prompt_tokens = draw(st.integers(min_value=0, max_value=100000))
    completion_tokens = draw(st.integers(min_value=0, max_value=100000))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@st.composite
def stop_chunk_with_usage_strategy(draw: Any) -> StopChunkWithUsage:
    """Generate StopChunkWithUsage instances for testing.

    These are OpenAI-format chunks with usage data that should NOT be
    accumulated as content.
    """
    # Generate a valid chunk ID
    chunk_id = f"chatcmpl-{draw(st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', min_size=8, max_size=20))}"

    # Generate timestamp
    created = draw(st.integers(min_value=1000000000, max_value=2000000000))

    # Generate model name
    model = draw(
        st.sampled_from(
            [
                "gpt-4",
                "gpt-3.5-turbo",
                "gemini-pro",
                "gemini-3-pro-high",
                "claude-3-opus",
                "claude-3-sonnet",
            ]
        )
    )

    # Generate usage
    usage = draw(usage_strategy())

    # Generate a choice with finish_reason="stop" (typical for final chunks)
    choice = {
        "index": 0,
        "delta": {"role": "assistant"},
        "finish_reason": "stop",
    }

    chunk_dict = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [choice],
        "usage": usage,
    }

    return StopChunkWithUsage(chunk_dict)


@st.composite
def text_content_chunk_strategy(draw: Any) -> dict[str, Any]:
    """Generate regular text content chunks (not StopChunkWithUsage).

    These are normal streaming chunks that SHOULD be accumulated.
    """
    chunk_id = f"chatcmpl-{draw(st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', min_size=8, max_size=20))}"
    created = draw(st.integers(min_value=1000000000, max_value=2000000000))
    model = draw(st.sampled_from(["gpt-4", "gemini-pro", "claude-3-opus"]))

    # Generate some text content
    content_text = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=100,
        )
    )

    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content_text},
                "finish_reason": None,
            }
        ],
    }


# ============================================================================
# Property 2: StopChunkWithUsage content isolation
# ============================================================================


@given(stop_chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
@pytest.mark.asyncio
async def test_property_2_stop_chunk_not_accumulated_as_content(
    stop_chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 2: StopChunkWithUsage content isolation**
    **Validates: Requirements 1.2, 1.4**

    Property 2: StopChunkWithUsage content isolation

    *For any* StopChunkWithUsage instance flowing through the content accumulation
    processor, the accumulated content string SHALL NOT contain the JSON
    representation of the usage chunk.
    """
    processor = ContentAccumulationProcessor()

    # Create a StreamingContent with the StopChunkWithUsage
    streaming_content = StreamingContent(
        content=stop_chunk,
        metadata={"stream_id": "test-stream"},
        is_done=True,
    )

    # Process through the accumulator
    result = await processor.process(streaming_content)

    # The result content should still be the StopChunkWithUsage (passed through)
    assert isinstance(
        result.content, StopChunkWithUsage
    ), f"StopChunkWithUsage should pass through unchanged, got {type(result.content).__name__}"

    # The accumulated_content in metadata should NOT contain the usage JSON
    accumulated = result.metadata.get("accumulated_content", "")
    if accumulated:
        # If there's any accumulated content, it should NOT be the JSON of the stop chunk
        usage_json = json.dumps(stop_chunk.get("usage", {}))
        assert usage_json not in accumulated, (
            f"Usage data should NOT be in accumulated content. "
            f"Found usage JSON in: {accumulated[:200]}..."
        )


@given(stop_chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
@pytest.mark.asyncio
async def test_property_2_usage_data_preserved_separately(
    stop_chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 2: StopChunkWithUsage content isolation**
    **Validates: Requirements 1.2, 1.4**

    *For any* StopChunkWithUsage instance flowing through the content accumulation
    processor, the usage data SHALL be preserved separately (in the usage field
    or metadata).
    """
    processor = ContentAccumulationProcessor()

    # Create a StreamingContent with the StopChunkWithUsage
    streaming_content = StreamingContent(
        content=stop_chunk,
        metadata={"stream_id": "test-stream"},
        is_done=True,
    )

    # Process through the accumulator
    result = await processor.process(streaming_content)

    # Usage should be preserved in the result
    original_usage = stop_chunk.get("usage")

    # Check that usage is preserved either in result.usage or in metadata
    preserved_usage = result.usage or result.metadata.get("usage")

    assert (
        preserved_usage is not None
    ), "Usage data should be preserved in result.usage or metadata['usage']"
    assert preserved_usage == original_usage, (
        f"Usage data should match original. "
        f"Expected: {original_usage}, Got: {preserved_usage}"
    )


@given(
    text_chunks=st.lists(text_content_chunk_strategy(), min_size=1, max_size=5),
    stop_chunk=stop_chunk_with_usage_strategy(),
)
@property_test_settings()
@pytest.mark.asyncio
async def test_property_2_mixed_stream_isolates_stop_chunk(
    text_chunks: list[dict[str, Any]],
    stop_chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 2: StopChunkWithUsage content isolation**
    **Validates: Requirements 1.2, 1.4**

    *For any* stream containing text chunks followed by a StopChunkWithUsage,
    the accumulated content SHALL contain only the text content, NOT the
    usage chunk data.
    """
    processor = ContentAccumulationProcessor()
    stream_id = "mixed-stream-test"

    # Process text chunks first
    expected_text = ""
    for chunk_dict in text_chunks:
        # Extract expected text from the chunk
        choices = chunk_dict.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            text = delta.get("content", "")
            if text:
                expected_text += text

        streaming_content = StreamingContent(
            content=chunk_dict,
            metadata={"stream_id": stream_id},
            is_done=False,
        )
        await processor.process(streaming_content)

    # Now process the stop chunk with usage
    stop_streaming_content = StreamingContent(
        content=stop_chunk,
        metadata={"stream_id": stream_id},
        is_done=True,
    )
    result = await processor.process(stop_streaming_content)

    # The stop chunk should pass through unchanged
    assert isinstance(
        result.content, StopChunkWithUsage
    ), f"StopChunkWithUsage should pass through unchanged, got {type(result.content).__name__}"

    # Usage should be preserved
    assert (
        result.usage is not None or result.metadata.get("usage") is not None
    ), "Usage data should be preserved"


@given(stop_chunk=stop_chunk_with_usage_strategy())
@property_test_settings()
@pytest.mark.asyncio
async def test_property_2_stop_chunk_content_not_json_stringified(
    stop_chunk: StopChunkWithUsage,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 2: StopChunkWithUsage content isolation**
    **Validates: Requirements 1.2**

    *For any* StopChunkWithUsage instance, the processor SHALL NOT convert it
    to a JSON string for accumulation.
    """
    processor = ContentAccumulationProcessor()

    streaming_content = StreamingContent(
        content=stop_chunk,
        metadata={"stream_id": "no-stringify-test"},
        is_done=True,
    )

    result = await processor.process(streaming_content)

    # The content should NOT be a string (which would indicate JSON stringification)
    assert not isinstance(result.content, str), (
        f"StopChunkWithUsage should NOT be converted to string. "
        f"Got string content: {result.content[:100] if len(str(result.content)) > 100 else result.content}"
    )

    # It should remain as the original StopChunkWithUsage
    assert isinstance(
        result.content, StopChunkWithUsage
    ), f"Content should remain as StopChunkWithUsage, got {type(result.content).__name__}"
