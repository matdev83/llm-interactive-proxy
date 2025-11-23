"""
Property-based tests for SSE Assembler.

This module contains property-based tests that verify the correctness
properties of the SSE assembler implementation.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import SentinelManager, StreamingContent


# Helper function to create async iterator from list
async def async_iter(items: list[Any]) -> Any:
    """Convert a list to an async iterator."""
    for item in items:
        yield item


# Strategy for generating valid metadata
def metadata_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Generate valid metadata dictionaries.

    Returns:
        Strategy for generating metadata that passes validation
    """
    # Build metadata field by field to ensure type correctness
    return st.fixed_dictionaries(
        {},
        optional={
            "provider": st.text(min_size=1, max_size=20),
            "model": st.text(min_size=1, max_size=20),
            "role": st.sampled_from(["assistant", "user", "system"]),
            "finish_reason": st.sampled_from(["stop", "length", "tool_calls", None]),
            "stream_id": st.text(min_size=1, max_size=20),
            "index": st.integers(min_value=0, max_value=10),
            "created": st.integers(min_value=1000000000, max_value=2000000000),
            "id": st.text(min_size=1, max_size=30),
        },
    )


# Strategy for generating StreamingContent chunks
def streaming_content_strategy(
    include_done: bool = False,
    min_chunks: int = 0,
    max_chunks: int = 20,
) -> st.SearchStrategy[list[StreamingContent]]:
    """Generate lists of StreamingContent chunks.

    Args:
        include_done: Whether to include a done marker at the end
        min_chunks: Minimum number of chunks
        max_chunks: Maximum number of chunks

    Returns:
        Strategy for generating chunk lists
    """
    chunk_strategy = st.builds(
        StreamingContent,
        content=st.one_of(
            st.text(min_size=0, max_size=100),
            st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=5),
        ),
        metadata=metadata_strategy(),
        is_done=st.just(False),
        is_empty=st.booleans(),
        stream_id=st.one_of(st.text(min_size=1, max_size=20), st.none()),
    )

    chunks_strategy = st.lists(
        chunk_strategy,
        min_size=min_chunks,
        max_size=max_chunks,
    )

    if include_done:
        # Add a done marker at the end
        return chunks_strategy.map(
            lambda chunks: [*chunks, SentinelManager.create_done_chunk()]
        )
    else:
        return chunks_strategy


@pytest.mark.asyncio
@given(
    chunks=streaming_content_strategy(include_done=True, min_chunks=1, max_chunks=20)
)
@settings(max_examples=100, deadline=None)
async def test_sentinel_utility_usage_property(chunks: list[StreamingContent]) -> None:
    """
    Property 14: Sentinel utility usage
    Feature: streaming-pipeline-refactor, Property 14: Sentinel utility usage

    For any stream completion, the [DONE] marker should be created using
    SentinelManager.create_done_chunk() and not ad-hoc string literals.

    This test verifies that:
    1. The assembler uses SentinelManager.format_sse_done() for the sentinel
    2. The sentinel is properly formatted as SSE
    3. No ad-hoc [DONE] strings are used

    Validates: Requirements 6.1, 6.3
    """
    # Arrange
    assembler = SSEAssembler()
    stream = async_iter(chunks)

    # Act
    result_chunks = []
    async for chunk_bytes in assembler.assemble_stream(stream, format="sse"):
        result_chunks.append(chunk_bytes)

    # Assert
    # The last chunk should be the standardized [DONE] marker
    assert len(result_chunks) > 0, "Stream should emit at least one chunk"

    last_chunk = result_chunks[-1]
    expected_done = SentinelManager.format_sse_done()

    # Verify the sentinel is exactly what SentinelManager produces
    assert last_chunk == expected_done, (
        f"Last chunk should be SentinelManager.format_sse_done(), "
        f"got {last_chunk!r}, expected {expected_done!r}"
    )

    # Verify the sentinel format is correct SSE format
    assert (
        last_chunk == b"data: [DONE]\n\n"
    ), "Sentinel should be in proper SSE format: 'data: [DONE]\\n\\n'"

    # Verify no other chunks contain ad-hoc [DONE] strings
    for i, chunk_bytes in enumerate(result_chunks[:-1]):
        # Check that [DONE] doesn't appear in non-terminal chunks
        if b"data: [DONE]\n\n" in chunk_bytes:
            pytest.fail(f"Chunk {i} contains ad-hoc [DONE] marker: {chunk_bytes!r}")


@pytest.mark.asyncio
@given(
    chunks_list=st.lists(
        streaming_content_strategy(include_done=True, min_chunks=1, max_chunks=15),
        min_size=2,
        max_size=5,
    )
)
@settings(max_examples=100, deadline=None)
async def test_sentinel_format_consistency_property(
    chunks_list: list[list[StreamingContent]],
) -> None:
    """
    Property 15: Sentinel format consistency
    Feature: streaming-pipeline-refactor, Property 15: Sentinel format consistency

    For any backend, the [DONE] sentinel should have identical format and
    metadata structure when emitted.

    This test verifies that:
    1. All streams emit the same [DONE] format
    2. The sentinel format is consistent across multiple streams
    3. The sentinel metadata structure is identical

    Validates: Requirements 6.2, 6.4
    """
    # Arrange
    assembler = SSEAssembler()
    sentinel_chunks = []

    # Act - Process multiple streams and collect their sentinels
    for chunks in chunks_list:
        stream = async_iter(chunks)
        result_chunks = []
        async for chunk_bytes in assembler.assemble_stream(stream, format="sse"):
            result_chunks.append(chunk_bytes)

        # The last chunk should be the sentinel
        if result_chunks:
            sentinel_chunks.append(result_chunks[-1])

    # Assert
    assert len(sentinel_chunks) > 0, "Should have collected at least one sentinel"

    # All sentinels should be identical
    first_sentinel = sentinel_chunks[0]
    for i, sentinel in enumerate(sentinel_chunks[1:], start=1):
        assert sentinel == first_sentinel, (
            f"Sentinel {i} differs from first sentinel. "
            f"Expected {first_sentinel!r}, got {sentinel!r}"
        )

    # All sentinels should match the SentinelManager format
    expected_sentinel = SentinelManager.format_sse_done()
    for i, sentinel in enumerate(sentinel_chunks):
        assert sentinel == expected_sentinel, (
            f"Sentinel {i} does not match SentinelManager.format_sse_done(). "
            f"Expected {expected_sentinel!r}, got {sentinel!r}"
        )

    # Verify the format is exactly "data: [DONE]\n\n"
    for i, sentinel in enumerate(sentinel_chunks):
        assert sentinel == b"data: [DONE]\n\n", (
            f"Sentinel {i} has incorrect format. "
            f"Expected b'data: [DONE]\\n\\n', got {sentinel!r}"
        )


@pytest.mark.asyncio
@given(
    chunks=streaming_content_strategy(include_done=True, min_chunks=0, max_chunks=20)
)
@settings(max_examples=100, deadline=None)
async def test_sse_format_framing(chunks: list[StreamingContent]) -> None:
    """
    Additional property test: Verify SSE framing is correct.

    This test verifies that all non-sentinel chunks are properly formatted
    as SSE with "data: " prefix and "\\n\\n" suffix.
    """
    # Arrange
    assembler = SSEAssembler()
    stream = async_iter(chunks)

    # Act
    result_chunks = []
    async for chunk_bytes in assembler.assemble_stream(stream, format="sse"):
        result_chunks.append(chunk_bytes)

    # Assert
    assert len(result_chunks) > 0, "Stream should emit at least one chunk"

    # All chunks should be bytes
    for i, chunk in enumerate(result_chunks):
        assert isinstance(chunk, bytes), f"Chunk {i} should be bytes, got {type(chunk)}"

    # The last chunk should be the [DONE] sentinel
    assert (
        result_chunks[-1] == b"data: [DONE]\n\n"
    ), "Last chunk should be [DONE] sentinel"

    # All non-sentinel chunks should have SSE framing
    for i, chunk in enumerate(result_chunks[:-1]):
        # Should start with "data: "
        assert chunk.startswith(
            b"data: "
        ), f"Chunk {i} should start with 'data: ', got {chunk[:10]!r}"

        # Should end with "\n\n"
        assert chunk.endswith(
            b"\n\n"
        ), f"Chunk {i} should end with '\\n\\n', got {chunk[-10:]!r}"


@pytest.mark.asyncio
@given(
    chunks=streaming_content_strategy(include_done=False, min_chunks=1, max_chunks=20)
)
@settings(max_examples=100, deadline=None)
async def test_sentinel_always_emitted(chunks: list[StreamingContent]) -> None:
    """
    Additional property test: Verify sentinel is always emitted.

    This test verifies that even if the input stream doesn't contain a done
    marker, the assembler still emits a [DONE] sentinel at the end.
    """
    # Arrange
    assembler = SSEAssembler()
    stream = async_iter(chunks)

    # Act
    result_chunks = []
    async for chunk_bytes in assembler.assemble_stream(stream, format="sse"):
        result_chunks.append(chunk_bytes)

    # Assert
    assert len(result_chunks) > 0, "Stream should emit at least one chunk"

    # The last chunk should always be the [DONE] sentinel
    assert result_chunks[-1] == b"data: [DONE]\n\n", (
        "Last chunk should always be [DONE] sentinel, even if input stream "
        "doesn't contain a done marker"
    )


@pytest.mark.asyncio
async def test_empty_stream_emits_sentinel() -> None:
    """
    Edge case test: Verify empty stream still emits sentinel.

    This test verifies that even an empty stream emits the [DONE] sentinel.
    """
    # Arrange
    assembler = SSEAssembler()
    stream = async_iter([])

    # Act
    result_chunks = []
    async for chunk_bytes in assembler.assemble_stream(stream, format="sse"):
        result_chunks.append(chunk_bytes)

    # Assert
    assert len(result_chunks) == 1, "Empty stream should emit exactly one chunk"
    assert (
        result_chunks[0] == b"data: [DONE]\n\n"
    ), "Empty stream should emit [DONE] sentinel"


@pytest.mark.asyncio
async def test_unsupported_format_raises_error() -> None:
    """
    Test that unsupported formats raise ValueError.
    """
    # Arrange
    assembler = SSEAssembler()
    stream = async_iter([SentinelManager.create_done_chunk()])

    # Act & Assert
    with pytest.raises(ValueError, match="Unsupported format"):
        async for _ in assembler.assemble_stream(stream, format="json-lines"):
            pass
