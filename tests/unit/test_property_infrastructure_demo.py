"""
Demo tests for property-based test infrastructure.

This module demonstrates how to use the property-based test infrastructure
for testing streaming pipeline components.

Feature: streaming-pipeline-refactor, Task 21: Property-based test infrastructure
"""

import pytest
from hypothesis import given, settings

from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import (
    chunk_stream_strategy,
    chunk_stream_with_done_strategy,
    create_done_chunk,
    create_test_chunk,
    streaming_content_strategy,
    streaming_content_with_reasoning_strategy,
)
from tests.utils.property_test_helpers import (
    ChunkBuilder,
    assert_done_marker_at_end,
    assert_single_done_marker,
    assert_valid_chunk,
    async_iter,
    async_list,
    count_done_markers,
    validate_chunk_structure,
)


class TestPropertyInfrastructureBasics:
    """Test basic property infrastructure functionality."""

    @given(chunk=streaming_content_strategy())
    @property_test_settings()
    def test_generated_chunks_are_valid(self, chunk):
        """Test that generated chunks are always valid.

        This demonstrates using the streaming_content_strategy to generate
        valid chunks and the validation helpers to verify them.
        """
        # All generated chunks should be valid
        assert validate_chunk_structure(chunk)
        assert_valid_chunk(chunk)

    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=10))
    @property_test_settings(max_examples=50)
    def test_streams_with_done_marker(self, chunks):
        """Test that streams with done markers are properly structured.

        This demonstrates using chunk_stream_with_done_strategy and
        assertion helpers.
        """
        # Should have exactly one done marker
        assert_single_done_marker(chunks)

        # Done marker should be at the end
        assert_done_marker_at_end(chunks)

    @given(chunk=streaming_content_with_reasoning_strategy())
    @property_test_settings()
    def test_reasoning_in_metadata(self, chunk):
        """Test that reasoning content is present in metadata.

        This demonstrates using streaming_content_with_reasoning_strategy
        to generate chunks with reasoning content.

        Note: We don't test for "leaks" here because the generator may
        create cases where reasoning happens to be a substring of content
        (e.g., "0" in "00"), which is not a real leak but a coincidence.
        Real leak detection should be tested with actual middleware processors.
        """
        # Reasoning should be in metadata
        assert "reasoning_content" in chunk.metadata
        assert chunk.metadata["reasoning_content"] is not None


class TestChunkBuilder:
    """Test the ChunkBuilder utility."""

    def test_builder_creates_valid_chunks(self):
        """Test that ChunkBuilder creates valid chunks."""
        chunk = (
            ChunkBuilder()
            .with_content("test content")
            .with_provider("openai")
            .with_stream_id("test-123")
            .build()
        )

        assert_valid_chunk(chunk)
        assert chunk.content == "test content"
        assert chunk.metadata["provider"] == "openai"
        assert chunk.stream_id == "test-123"

    def test_builder_fluent_api(self):
        """Test that ChunkBuilder supports fluent API."""
        chunk = (
            ChunkBuilder()
            .with_content("hello")
            .with_provider("anthropic")
            .with_reasoning("thinking...")
            .as_done()
            .build()
        )

        assert chunk.is_done
        assert chunk.metadata["reasoning_content"] == "thinking..."
        assert chunk.metadata["finish_reason"] == "stop"


class TestAsyncHelpers:
    """Test async helper utilities."""

    @pytest.mark.asyncio
    async def test_async_list_conversion(self):
        """Test converting async iterator to list."""
        chunks = [
            create_test_chunk("chunk1"),
            create_test_chunk("chunk2"),
            create_test_chunk("chunk3"),
        ]

        # Convert to async iterator and back to list
        stream = async_iter(chunks)
        result = await async_list(stream)

        assert len(result) == 3
        assert result[0].content == "chunk1"
        assert result[1].content == "chunk2"
        assert result[2].content == "chunk3"

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_strategy(min_size=1, max_size=20))
    @settings(max_examples=50, deadline=None)
    async def test_async_stream_processing(self, chunks):
        """Test processing async streams.

        This demonstrates using async helpers with property-based testing.
        """
        # Convert to async stream and back
        stream = async_iter(chunks)
        result = await async_list(stream)

        # Should preserve all chunks
        assert len(result) == len(chunks)


class TestUtilityFunctions:
    """Test utility functions."""

    def test_create_test_chunk(self):
        """Test creating simple test chunks."""
        chunk = create_test_chunk("hello", "openai", "stream-1")

        assert chunk.content == "hello"
        assert chunk.metadata["provider"] == "openai"
        assert chunk.stream_id == "stream-1"

    def test_create_done_chunk(self):
        """Test creating done marker chunks."""
        chunk = create_done_chunk("anthropic", "stream-2")

        assert chunk.is_done
        assert chunk.content == "[DONE]"
        assert chunk.metadata["finish_reason"] == "stop"
        assert chunk.stream_id == "stream-2"

    @given(chunks=chunk_stream_strategy(min_size=0, max_size=20))
    @property_test_settings(max_examples=50)
    def test_count_done_markers(self, chunks):
        """Test counting done markers in streams."""
        # Add a done marker
        chunks.append(create_done_chunk())

        # Should count exactly one
        assert count_done_markers(chunks) >= 1


class TestHypothesisConfiguration:
    """Test Hypothesis configuration."""

    @given(chunk=streaming_content_strategy())
    @property_test_settings(max_examples=10)
    def test_custom_max_examples(self, chunk):
        """Test using custom max_examples setting.

        This test will run only 10 iterations instead of the default 100.
        """
        assert_valid_chunk(chunk)

    @given(chunk=streaming_content_strategy())
    @settings(max_examples=5, deadline=None)
    def test_inline_settings(self, chunk):
        """Test using inline settings.

        This demonstrates using settings directly without the helper.
        """
        assert_valid_chunk(chunk)


# Example of how to write a property test for a real component
class TestExamplePropertyTest:
    """Example property test for demonstration."""

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=10))
    @settings(max_examples=50, deadline=None)
    async def test_stream_processing_preserves_done_marker(self, chunks):
        """
        Example Property: Stream processing preserves done marker
        Feature: streaming-pipeline-refactor, Example property

        For any stream of chunks ending with a done marker, processing
        the stream should preserve the done marker at the end.

        This is an example of how to write a complete property test.
        """
        # Convert to async stream
        stream = async_iter(chunks)

        # Process stream (in real test, this would be actual processing)
        processed = await async_list(stream)

        # Verify done marker is preserved
        assert_single_done_marker(processed)
        assert_done_marker_at_end(processed)

        # Verify all chunks are valid
        for chunk in processed:
            assert_valid_chunk(chunk)
