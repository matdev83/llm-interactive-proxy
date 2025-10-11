"""
Tests for ContentAccumulationProcessor buffer limit protection.

This test suite validates that the ContentAccumulationProcessor properly
enforces buffer size limits to prevent memory leaks from unbounded streams.
"""

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)


class TestContentAccumulationBufferLimit:
    """Test buffer size limits in ContentAccumulationProcessor."""

    @pytest.mark.asyncio
    async def test_small_content_under_limit(self) -> None:
        """Test that small content under the limit is handled normally."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=1024)  # 1KB limit

        # Send small chunks
        chunk1 = StreamingContent(
            content="Hello ", metadata={"stream_id": "buffer-test-1"}
        )
        chunk2 = StreamingContent(
            content="World", metadata={"stream_id": "buffer-test-1"}
        )
        chunk3 = StreamingContent(
            content="!", is_done=True, metadata={"stream_id": "buffer-test-1"}
        )

        result1 = await processor.process(chunk1)
        assert result1.content == ""  # Buffered, not emitted yet

        result2 = await processor.process(chunk2)
        assert result2.content == ""  # Still buffered

        result3 = await processor.process(chunk3)
        assert result3.content == "Hello World!"
        assert result3.is_done

    @pytest.mark.asyncio
    async def test_content_exceeds_buffer_limit(self) -> None:
        """Test that content exceeding buffer limit is truncated."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=100)  # 100 bytes

        # Create content larger than 100 bytes
        large_content = "X" * 150  # 150 bytes
        chunk1 = StreamingContent(content=large_content)

        result1 = await processor.process(chunk1)
        # Should be empty since not done yet
        assert result1.content == ""

        # Check that buffer was truncated by verifying final output
        chunk2 = StreamingContent(content="Y" * 50, is_done=True)
        result2 = await processor.process(chunk2)

        # Buffer should have been truncated, output should be less than 150 + 50
        assert result2.is_done
        # The buffer was truncated, so we shouldn't have all 150 X's
        assert len(result2.content) < 200

    @pytest.mark.asyncio
    async def test_very_large_stream_memory_protection(self) -> None:
        """Test that very large streams don't cause unbounded memory growth."""
        # Use a small buffer limit for testing
        processor = ContentAccumulationProcessor(max_buffer_bytes=1024)  # 1KB

        # Simulate a very large stream (10KB of content)
        chunk_size = 500  # 500 bytes per chunk
        num_chunks = 20  # Total 10KB

        for i in range(num_chunks):
            content = f"Chunk {i}: " + ("X" * chunk_size)
            chunk = StreamingContent(content=content)
            result = await processor.process(chunk)
            # Should not emit content until done
            assert result.content == ""

        # Send final chunk
        final_chunk = StreamingContent(content="END", is_done=True)
        final_result = await processor.process(final_chunk)

        # Should have content but truncated to ~1KB
        assert final_result.is_done
        assert len(final_result.content) > 0
        # Verify it was truncated (should be around 1KB, not 10KB)
        content_bytes = len(final_result.content.encode("utf-8"))
        assert content_bytes <= 1024 * 1.2  # Allow 20% overhead for UTF-8 and rounding
        # Should contain recent chunks (from the end)
        assert "END" in final_result.content

    @pytest.mark.asyncio
    async def test_buffer_reset_after_stream_completion(self) -> None:
        """Test that buffer is properly reset after stream completes."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=1024)

        # First stream
        chunk1 = StreamingContent(content="Stream 1", is_done=True)
        result1 = await processor.process(chunk1)
        assert result1.content == "Stream 1"

        # Second stream should not contain data from first stream
        chunk2 = StreamingContent(content="Stream 2", is_done=True)
        result2 = await processor.process(chunk2)
        assert result2.content == "Stream 2"
        assert "Stream 1" not in result2.content

    @pytest.mark.asyncio
    async def test_empty_chunks_handled_correctly(self) -> None:
        """Test that empty chunks don't affect buffer limit logic."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=100)

        # Send empty chunks (content="" makes is_empty True automatically)
        empty_chunk = StreamingContent(content="")
        result = await processor.process(empty_chunk)
        assert result.content == ""
        assert result.is_empty

        # Send real content
        content_chunk = StreamingContent(content="Hello", is_done=True)
        result = await processor.process(content_chunk)
        assert result.content == "Hello"

    @pytest.mark.asyncio
    async def test_metadata_preserved_during_accumulation(self) -> None:
        """Test that metadata is preserved through the accumulation process."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=1024)

        metadata = {"key": "value"}
        usage = {"tokens": 100}

        chunk = StreamingContent(content="test", metadata=metadata, usage=usage)
        result = await processor.process(chunk)

        # Metadata should be preserved even though content is buffered
        assert result.metadata == metadata
        assert result.usage == usage

    @pytest.mark.asyncio
    async def test_unicode_content_buffer_calculation(self) -> None:
        """Test that buffer size is calculated correctly for Unicode content."""
        processor = ContentAccumulationProcessor(max_buffer_bytes=100)

        # Unicode characters can be multiple bytes (use non-emoji to avoid emoji rule)
        unicode_content = (
            "Ł" * 100
        )  # Polish letter (2 bytes in UTF-8 ~ 200 bytes total)
        chunk = StreamingContent(content=unicode_content)

        result = await processor.process(chunk)
        assert result.content == ""  # Buffered

        # Should trigger truncation
        final_chunk = StreamingContent(content="", is_done=True)
        final_result = await processor.process(final_chunk)

        # Should be truncated
        content_bytes = len(final_result.content.encode("utf-8"))
        assert content_bytes <= 120  # Should be around 100 bytes, not 200

    @pytest.mark.asyncio
    async def test_default_buffer_size(self) -> None:
        """Test that default buffer size is reasonable."""
        processor = ContentAccumulationProcessor()  # Use default

        # Default should be 10MB, so this should fit
        content = "X" * 1000000  # 1MB
        chunk = StreamingContent(content=content, is_done=True)
        result = await processor.process(chunk)

        # Should not be truncated
        assert len(result.content) == 1000000
