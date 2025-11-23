"""
Helper utilities for property-based testing.

This module provides utility functions and classes to support property-based
testing of the streaming pipeline.

Feature: streaming-pipeline-refactor, Task 21: Property-based test infrastructure
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from src.core.ports.streaming_contracts import StreamingContent

# ============================================================================
# Async Utilities
# ============================================================================


async def async_list(async_iter: AsyncIterator[Any]) -> list[Any]:
    """Convert an async iterator to a list.

    Args:
        async_iter: The async iterator to convert

    Returns:
        A list of all items from the iterator
    """
    result = []
    async for item in async_iter:
        result.append(item)
    return result


async def async_iter(items: list[Any]) -> AsyncIterator[Any]:
    """Convert a list to an async iterator.

    Args:
        items: The list to convert

    Yields:
        Items from the list
    """
    for item in items:
        yield item
        # Yield control to event loop
        await asyncio.sleep(0)


async def async_iter_with_delay(
    items: list[Any], delay: float = 0.001
) -> AsyncIterator[Any]:
    """Convert a list to an async iterator with delays.

    This is useful for testing backpressure and streaming behavior.

    Args:
        items: The list to convert
        delay: Delay in seconds between items

    Yields:
        Items from the list with delays
    """
    for item in items:
        yield item
        await asyncio.sleep(delay)


# ============================================================================
# Chunk Validation Utilities
# ============================================================================


def validate_chunk_structure(chunk: StreamingContent) -> bool:
    """Validate that a chunk has the correct structure.

    Args:
        chunk: The chunk to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        # Check required attributes
        assert hasattr(chunk, "content"), "Missing content attribute"
        assert hasattr(chunk, "metadata"), "Missing metadata attribute"
        assert hasattr(chunk, "is_done"), "Missing is_done attribute"
        assert hasattr(chunk, "is_empty"), "Missing is_empty attribute"
        assert hasattr(chunk, "stream_id"), "Missing stream_id attribute"
        assert hasattr(chunk, "is_cancellation"), "Missing is_cancellation attribute"

        # Check types
        assert isinstance(chunk.content, str | dict | bytes), "Invalid content type"
        assert isinstance(chunk.metadata, dict), "Invalid metadata type"
        assert isinstance(chunk.is_done, bool), "Invalid is_done type"
        assert isinstance(chunk.is_empty, bool), "Invalid is_empty type"
        assert isinstance(chunk.is_cancellation, bool), "Invalid is_cancellation type"
        assert chunk.stream_id is None or isinstance(
            chunk.stream_id, str
        ), "Invalid stream_id type"

        return True
    except AssertionError:
        return False


def validate_metadata_schema(metadata: dict[str, Any]) -> bool:
    """Validate that metadata conforms to the schema.

    Args:
        metadata: The metadata to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        # Check optional fields have correct types
        if "stream_id" in metadata:
            assert isinstance(metadata["stream_id"], str), "stream_id must be str"

        if "provider" in metadata:
            assert isinstance(metadata["provider"], str), "provider must be str"

        if "model" in metadata:
            assert isinstance(metadata["model"], str), "model must be str"

        if "role" in metadata:
            assert isinstance(metadata["role"], str), "role must be str"

        if "finish_reason" in metadata:
            finish_reason = metadata["finish_reason"]
            assert finish_reason is None or isinstance(
                finish_reason, str
            ), "finish_reason must be None or str"

        if "reasoning_content" in metadata:
            reasoning = metadata["reasoning_content"]
            assert reasoning is None or isinstance(
                reasoning, str
            ), "reasoning_content must be None or str"

        if "tool_calls" in metadata:
            assert isinstance(metadata["tool_calls"], list), "tool_calls must be list"

        if "index" in metadata:
            assert isinstance(metadata["index"], int), "index must be int"

        if "created" in metadata:
            assert isinstance(metadata["created"], int), "created must be int"

        if "id" in metadata:
            assert isinstance(metadata["id"], str), "id must be str"

        return True
    except AssertionError:
        return False


def count_done_markers(chunks: list[StreamingContent]) -> int:
    """Count the number of done markers in a list of chunks.

    Args:
        chunks: The list of chunks to check

    Returns:
        The number of done markers
    """
    return sum(1 for chunk in chunks if chunk.is_done)


def has_reasoning_in_content(chunk: StreamingContent) -> bool:
    """Check if reasoning content leaked into main content.

    Args:
        chunk: The chunk to check

    Returns:
        True if reasoning is in main content, False otherwise
    """
    if not isinstance(chunk.content, str):
        return False

    reasoning = chunk.metadata.get("reasoning_content")
    if not reasoning or not isinstance(reasoning, str):
        return False

    return reasoning in chunk.content


# ============================================================================
# Stream Processing Utilities
# ============================================================================


async def process_stream_to_list(
    stream: AsyncIterator[StreamingContent],
) -> list[StreamingContent]:
    """Process an async stream and collect all chunks.

    Args:
        stream: The stream to process

    Returns:
        A list of all chunks from the stream
    """
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return chunks


async def filter_stream(
    stream: AsyncIterator[StreamingContent],
    predicate: callable,
) -> AsyncIterator[StreamingContent]:
    """Filter a stream based on a predicate.

    Args:
        stream: The stream to filter
        predicate: Function that returns True for chunks to keep

    Yields:
        Chunks that match the predicate
    """
    async for chunk in stream:
        if predicate(chunk):
            yield chunk


async def map_stream(
    stream: AsyncIterator[StreamingContent],
    transform: callable,
) -> AsyncIterator[StreamingContent]:
    """Map a transformation over a stream.

    Args:
        stream: The stream to transform
        transform: Function to apply to each chunk

    Yields:
        Transformed chunks
    """
    async for chunk in stream:
        yield transform(chunk)


# ============================================================================
# Comparison Utilities
# ============================================================================


def chunks_equal(chunk1: StreamingContent, chunk2: StreamingContent) -> bool:
    """Check if two chunks are equal.

    Args:
        chunk1: First chunk
        chunk2: Second chunk

    Returns:
        True if chunks are equal, False otherwise
    """
    return (
        chunk1.content == chunk2.content
        and chunk1.metadata == chunk2.metadata
        and chunk1.is_done == chunk2.is_done
        and chunk1.is_empty == chunk2.is_empty
        and chunk1.stream_id == chunk2.stream_id
        and chunk1.is_cancellation == chunk2.is_cancellation
    )


def metadata_subset(metadata1: dict[str, Any], metadata2: dict[str, Any]) -> bool:
    """Check if metadata1 is a subset of metadata2.

    Args:
        metadata1: The subset metadata
        metadata2: The superset metadata

    Returns:
        True if metadata1 is a subset of metadata2
    """
    for key, value in metadata1.items():
        if key not in metadata2:
            return False
        if metadata2[key] != value:
            return False
    return True


# ============================================================================
# Mock Processors for Testing
# ============================================================================


class PassThroughProcessor:
    """A processor that passes chunks through unchanged."""

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Pass through the content unchanged.

        Args:
            content: The content to process

        Returns:
            The same content
        """
        return content

    def reset(self) -> None:
        """Reset processor state (no-op for pass-through)."""


class CountingProcessor:
    """A processor that counts chunks processed."""

    def __init__(self):
        """Initialize the counting processor."""
        self.count = 0
        self.done_count = 0

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Count the chunk and pass it through.

        Args:
            content: The content to process

        Returns:
            The same content
        """
        self.count += 1
        if content.is_done:
            self.done_count += 1
        return content

    def reset(self) -> None:
        """Reset the counters."""
        self.count = 0
        self.done_count = 0


class MetadataEnrichingProcessor:
    """A processor that adds metadata to chunks."""

    def __init__(self, key: str, value: Any):
        """Initialize the enriching processor.

        Args:
            key: The metadata key to add
            value: The value to set
        """
        self.key = key
        self.value = value

    async def process(self, content: StreamingContent) -> StreamingContent:
        """Add metadata to the chunk.

        Args:
            content: The content to process

        Returns:
            The content with enriched metadata
        """
        content.metadata[self.key] = self.value
        return content

    def reset(self) -> None:
        """Reset processor state (no-op for stateless processor)."""


# ============================================================================
# Assertion Helpers
# ============================================================================


def assert_valid_chunk(chunk: StreamingContent) -> None:
    """Assert that a chunk is valid.

    Args:
        chunk: The chunk to validate

    Raises:
        AssertionError: If the chunk is invalid
    """
    assert validate_chunk_structure(chunk), "Chunk structure is invalid"
    assert validate_metadata_schema(chunk.metadata), "Metadata schema is invalid"


def assert_no_reasoning_leak(chunk: StreamingContent) -> None:
    """Assert that reasoning content hasn't leaked into main content.

    Args:
        chunk: The chunk to check

    Raises:
        AssertionError: If reasoning leaked into content
    """
    assert not has_reasoning_in_content(
        chunk
    ), "Reasoning content leaked into main content"


def assert_single_done_marker(chunks: list[StreamingContent]) -> None:
    """Assert that there is exactly one done marker.

    Args:
        chunks: The list of chunks to check

    Raises:
        AssertionError: If there is not exactly one done marker
    """
    done_count = count_done_markers(chunks)
    assert done_count == 1, f"Expected 1 done marker, got {done_count}"


def assert_done_marker_at_end(chunks: list[StreamingContent]) -> None:
    """Assert that the done marker is at the end of the stream.

    Args:
        chunks: The list of chunks to check

    Raises:
        AssertionError: If the done marker is not at the end
    """
    if not chunks:
        return

    # Check that only the last chunk is done
    for i, chunk in enumerate(chunks[:-1]):
        assert not chunk.is_done, f"Chunk at index {i} is done but not at end"

    # Check that the last chunk is done
    assert chunks[-1].is_done, "Last chunk is not done"


# ============================================================================
# Test Data Builders
# ============================================================================


class ChunkBuilder:
    """Builder for creating test chunks with fluent API."""

    def __init__(self):
        """Initialize the chunk builder."""
        self._content = ""
        self._metadata: dict[str, Any] = {}
        self._is_done = False
        self._is_empty = False
        self._stream_id: str | None = None
        self._is_cancellation = False

    def with_content(self, content: str | dict | bytes) -> "ChunkBuilder":
        """Set the content.

        Args:
            content: The content to set

        Returns:
            Self for chaining
        """
        self._content = content
        return self

    def with_metadata(self, metadata: dict[str, Any]) -> "ChunkBuilder":
        """Set the metadata.

        Args:
            metadata: The metadata to set

        Returns:
            Self for chaining
        """
        self._metadata = metadata
        return self

    def with_provider(self, provider: str) -> "ChunkBuilder":
        """Set the provider in metadata.

        Args:
            provider: The provider name

        Returns:
            Self for chaining
        """
        self._metadata["provider"] = provider
        return self

    def with_stream_id(self, stream_id: str) -> "ChunkBuilder":
        """Set the stream ID.

        Args:
            stream_id: The stream ID

        Returns:
            Self for chaining
        """
        self._stream_id = stream_id
        self._metadata["stream_id"] = stream_id
        return self

    def as_done(self) -> "ChunkBuilder":
        """Mark as done.

        Returns:
            Self for chaining
        """
        self._is_done = True
        self._metadata["finish_reason"] = "stop"
        return self

    def as_empty(self) -> "ChunkBuilder":
        """Mark as empty.

        Returns:
            Self for chaining
        """
        self._is_empty = True
        return self

    def with_reasoning(self, reasoning: str) -> "ChunkBuilder":
        """Add reasoning content to metadata.

        Args:
            reasoning: The reasoning text

        Returns:
            Self for chaining
        """
        self._metadata["reasoning_content"] = reasoning
        return self

    def build(self) -> StreamingContent:
        """Build the chunk.

        Returns:
            The constructed StreamingContent
        """
        return StreamingContent(
            content=self._content,
            metadata=self._metadata,
            is_done=self._is_done,
            is_empty=self._is_empty,
            stream_id=self._stream_id,
            is_cancellation=self._is_cancellation,
        )
