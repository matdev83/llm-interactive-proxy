"""
Comprehensive Tests for ResponseBuffer.

This module provides comprehensive test coverage for the ResponseBuffer class.
"""

from collections import deque

import pytest
from src.loop_detection.buffer import ResponseBuffer


class TestResponseBuffer:
    """Comprehensive tests for ResponseBuffer class."""

    @pytest.fixture
    def buffer(self) -> ResponseBuffer:
        """Create a fresh ResponseBuffer for each test."""
        return ResponseBuffer(max_size=100)

    def test_initialization(self) -> None:
        """Test buffer initialization."""
        buffer = ResponseBuffer(max_size=50)

        assert buffer.max_size == 50
        assert buffer.buffer == deque()
        assert buffer.total_length == 0
        assert buffer.stored_length == 0

    def test_initialization_default_max_size(self) -> None:
        """Test buffer initialization with default max size."""
        buffer = ResponseBuffer()

        assert buffer.max_size == 2048  # Default from original implementation
        assert buffer.buffer == deque()
        assert buffer.total_length == 0
        assert buffer.stored_length == 0

    def test_append_single_chunk(self, buffer: ResponseBuffer) -> None:
        """Test appending a single chunk."""
        chunk = "Hello, world!"
        buffer.append(chunk)

        assert len(buffer.buffer) == 1
        assert buffer.stored_length == len(chunk)
        assert buffer.total_length == len(chunk)
        assert buffer.get_content() == chunk

    def test_append_multiple_chunks(self, buffer: ResponseBuffer) -> None:
        """Test appending multiple chunks."""
        chunks = ["Hello, ", "world!", " How are you?"]

        for chunk in chunks:
            buffer.append(chunk)

        expected_content = "".join(chunks)
        assert buffer.get_content() == expected_content
        assert buffer.stored_length == len(expected_content)
        assert buffer.total_length == len(expected_content)
        assert len(buffer.buffer) == len(chunks)

    def test_append_empty_chunk(self, buffer: ResponseBuffer) -> None:
        """Test appending empty chunk."""
        buffer.append("")
        buffer.append("content")

        assert buffer.get_content() == "content"
        assert buffer.stored_length == len("content")
        assert buffer.total_length == len("content")

    def test_append_none_chunk(self, buffer: ResponseBuffer) -> None:
        """Test appending None (should be ignored)."""
        buffer.append(None)  # type: ignore
        buffer.append("content")

        assert buffer.get_content() == "content"

    def test_buffer_overflow_single_large_chunk(self) -> None:
        """Test buffer overflow with single large chunk."""
        buffer = ResponseBuffer(max_size=10)

        large_chunk = "This is a very long chunk that exceeds buffer size"
        buffer.append(large_chunk)

        assert len(buffer.get_content()) <= buffer.max_size
        assert buffer.stored_length <= buffer.max_size
        assert buffer.total_length == len(large_chunk)  # Total should track everything

    def test_buffer_overflow_multiple_chunks(self) -> None:
        """Test buffer overflow with multiple chunks."""
        buffer = ResponseBuffer(max_size=20)

        chunks = ["chunk1", "chunk2", "chunk3", "chunk4"]
        for chunk in chunks:
            buffer.append(chunk)

        content = buffer.get_content()
        assert len(content) <= buffer.max_size
        assert buffer.stored_length <= buffer.max_size
        assert buffer.total_length == len("".join(chunks))

    def test_buffer_partial_chunk_removal(self) -> None:
        """Test partial removal of chunks when buffer overflows."""
        buffer = ResponseBuffer(max_size=15)

        # First chunk fits
        buffer.append("1234567890")  # 10 chars
        assert buffer.stored_length == 10

        # Second chunk causes overflow
        buffer.append("ABCDEFGHIJ")  # 10 chars, total 20 > 15

        content = buffer.get_content()
        # Should have removed 5 characters from the beginning
        assert len(content) == 15
        assert content.endswith("ABCDEFGHIJ")  # Second chunk should be complete
        assert content.startswith("67890")  # Partial first chunk

    def test_get_recent_content(self, buffer: ResponseBuffer) -> None:
        """Test get_recent_content method."""
        long_content = "This is a long piece of content for testing"
        buffer.append(long_content)

        # Get recent content
        recent = buffer.get_recent_content(10)
        assert recent == long_content[-10:]
        assert len(recent) == 10

    def test_get_recent_content_full_content(self, buffer: ResponseBuffer) -> None:
        """Test get_recent_content when requesting more than available."""
        content = "short content"
        buffer.append(content)

        recent = buffer.get_recent_content(100)
        assert recent == content

    def test_get_recent_content_empty_buffer(self, buffer: ResponseBuffer) -> None:
        """Test get_recent_content on empty buffer."""
        recent = buffer.get_recent_content(10)
        assert recent == ""

    def test_clear_buffer(self, buffer: ResponseBuffer) -> None:
        """Test clearing the buffer."""
        buffer.append("some content")
        assert buffer.stored_length > 0

        buffer.clear()

        assert buffer.stored_length == 0
        assert buffer.total_length == 0
        assert len(buffer.buffer) == 0
        assert buffer.get_content() == ""

    def test_size_method(self, buffer: ResponseBuffer) -> None:
        """Test size method."""
        assert buffer.size() == 0

        buffer.append("hello")
        assert buffer.size() == 5

        buffer.append(" world")
        assert buffer.size() == 11

    def test_unicode_content(self, buffer: ResponseBuffer) -> None:
        """Test handling of Unicode content."""
        unicode_text = "Hello, 世界! 🌍"
        buffer.append(unicode_text)

        assert buffer.get_content() == unicode_text
        assert buffer.stored_length == len(unicode_text)

    def test_mixed_chunk_sizes(self, buffer: ResponseBuffer) -> None:
        """Test with mixed chunk sizes."""
        chunks = ["a", "bb", "ccc", "dddd", "eeeee"]
        for chunk in chunks:
            buffer.append(chunk)

        expected = "".join(chunks)
        assert buffer.get_content() == expected
        assert buffer.stored_length == len(expected)

    def test_chunk_with_newlines(self, buffer: ResponseBuffer) -> None:
        """Test chunks containing newlines."""
        chunk = "Line 1\nLine 2\nLine 3"
        buffer.append(chunk)

        assert buffer.get_content() == chunk
        assert "\n" in buffer.get_content()

    def test_zero_max_size_buffer(self) -> None:
        """Test buffer with zero max size."""
        buffer = ResponseBuffer(max_size=0)

        buffer.append("content")

        # Should have no stored content
        assert buffer.stored_length == 0
        assert buffer.get_content() == ""
        assert buffer.total_length == len("content")  # But total should track

    def test_very_small_max_size(self) -> None:
        """Test buffer with very small max size."""
        buffer = ResponseBuffer(max_size=1)

        buffer.append("abc")

        assert buffer.stored_length == 1
        assert len(buffer.get_content()) == 1
        assert buffer.total_length == 3

    def test_exact_max_size_fit(self, buffer: ResponseBuffer) -> None:
        """Test when content fits exactly in max size."""
        content = "x" * buffer.max_size
        buffer.append(content)

        assert buffer.stored_length == buffer.max_size
        assert len(buffer.get_content()) == buffer.max_size
        assert buffer.get_content() == content

    def test_multiple_appends_exceeding_max_size(self) -> None:
        """Test multiple appends that collectively exceed max size."""
        buffer = ResponseBuffer(max_size=5)

        # First append fits
        buffer.append("123")
        assert buffer.stored_length == 3

        # Second append causes overflow
        buffer.append("456789")
        assert buffer.stored_length == 5  # Should be at max
        assert len(buffer.get_content()) == 5

    def test_buffer_state_consistency(self, buffer: ResponseBuffer) -> None:
        """Test that buffer state remains consistent after operations."""
        initial_state = (buffer.stored_length, buffer.total_length, len(buffer.buffer))

        buffer.append("test")
        buffer.append("content")

        # State should be updated
        assert buffer.stored_length > initial_state[0]
        assert buffer.total_length > initial_state[1]
        assert len(buffer.buffer) > initial_state[2]

        # Get content shouldn't change state
        content = buffer.get_content()
        assert buffer.stored_length == len(content)
        assert buffer.total_length == len("testcontent")

    def test_get_content_returns_copy(self, buffer: ResponseBuffer) -> None:
        """Test that get_content returns consistent content."""
        buffer.append("test content")

        content1 = buffer.get_content()
        content2 = buffer.get_content()

        assert content1 == content2
        # Note: Python may intern small strings, so we don't test object identity

    def test_get_recent_content_edge_cases(self, buffer: ResponseBuffer) -> None:
        """Test edge cases for get_recent_content."""
        # Empty buffer
        assert buffer.get_recent_content(0) == ""
        assert buffer.get_recent_content(-1) == ""  # Negative should return empty

        # Content smaller than requested
        buffer.append("abc")
        assert buffer.get_recent_content(5) == "abc"

        # Exact size match
        buffer.clear()
        buffer.append("abcde")
        assert buffer.get_recent_content(5) == "abcde"

    def test_buffer_with_special_characters(self, buffer: ResponseBuffer) -> None:
        """Test buffer with special characters."""
        special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        buffer.append(special)

        assert buffer.get_content() == special
        assert buffer.stored_length == len(special)

    def test_large_number_of_small_chunks(self) -> None:
        """Test performance with many small chunks."""
        buffer = ResponseBuffer(max_size=100)

        # Add many small chunks
        for _i in range(50):
            buffer.append("x")

        content = buffer.get_content()
        assert len(content) <= 100
        assert buffer.stored_length <= 100
        assert buffer.total_length == 50

    def test_chunk_size_variations(self, buffer: ResponseBuffer) -> None:
        """Test various chunk sizes to ensure proper handling."""
        sizes = [1, 5, 10, 50, 100]
        chunks = [f"{'x' * size}" for size in sizes]

        for chunk in chunks:
            buffer.append(chunk)

        content = buffer.get_content()
        assert len(content) <= buffer.max_size
        assert buffer.total_length == sum(sizes)

    def test_buffer_efficiency(self) -> None:
        """Test buffer efficiency in managing memory."""
        buffer = ResponseBuffer(max_size=10)

        # Add content that will cause multiple evictions
        for _i in range(20):
            buffer.append("abc")  # 3 chars each

        # Should maintain max size
        assert buffer.stored_length <= 10

        # But total should track everything
        assert buffer.total_length == 20 * 3  # 60 chars total added

    def test_empty_and_whitespace_chunks(self, buffer: ResponseBuffer) -> None:
        """Test handling of empty and whitespace-only chunks."""
        chunks = ["", "   ", "\n", "\t", "content"]
        for chunk in chunks:
            buffer.append(chunk)

        content = buffer.get_content()
        assert "content" in content
        assert buffer.stored_length > 0


class TestResponseBufferEdgeCases:
    """Additional edge case tests for ResponseBuffer."""

    def test_max_size_boundary_conditions(self) -> None:
        """Test boundary conditions around max_size."""
        # Max size of 1
        buffer = ResponseBuffer(max_size=1)
        buffer.append("ab")
        assert buffer.get_content() == "b"
        assert buffer.stored_length == 1

        # Max size of 0
        buffer = ResponseBuffer(max_size=0)
        buffer.append("test")
        assert buffer.get_content() == ""
        assert buffer.stored_length == 0
        assert buffer.total_length == 4

    def test_sequential_operations(self) -> None:
        """Test sequence of operations."""
        buffer = ResponseBuffer(max_size=20)

        # Add content
        buffer.append("hello")
        assert buffer.get_content() == "hello"

        # Add more content
        buffer.append(" world")
        assert buffer.get_content() == "hello world"

        # Check size
        assert buffer.size() == len("hello world")

        # Clear
        buffer.clear()
        assert buffer.get_content() == ""
        assert buffer.size() == 0

        # Add again
        buffer.append("new content")
        assert buffer.get_content() == "new content"

    def test_content_preservation_during_overflow(self) -> None:
        """Test that content is properly preserved during overflow."""
        buffer = ResponseBuffer(max_size=5)

        # Add initial content
        buffer.append("12345")
        assert buffer.get_content() == "12345"

        # Add content that causes partial overflow
        buffer.append("67890")
        assert len(buffer.get_content()) == 5
        # Should preserve the most recent content
        assert buffer.get_content()[-3:] == "890"

    def test_total_length_tracking_accuracy(self) -> None:
        """Test that total_length accurately tracks all content."""
        buffer = ResponseBuffer(max_size=3)

        # Add multiple chunks
        chunks = ["ab", "cd", "ef", "gh"]
        for chunk in chunks:
            buffer.append(chunk)

        # Total should be sum of all chunk lengths
        expected_total = sum(len(chunk) for chunk in chunks)
        assert buffer.total_length == expected_total

        # Stored length should be <= max_size
        assert buffer.stored_length <= buffer.max_size

    def test_get_recent_content_with_overflow(self) -> None:
        """Test get_recent_content after buffer overflow."""
        buffer = ResponseBuffer(max_size=10)

        # Fill buffer beyond capacity
        buffer.append("very long content that will overflow")
        buffer.append("more content")

        # Recent content should still work correctly
        recent = buffer.get_recent_content(5)
        assert len(recent) == 5
        assert recent in buffer.get_content()

    def test_performance_with_many_chunks(self) -> None:
        """Test performance characteristics with many chunks."""
        buffer = ResponseBuffer(max_size=1000)

        # Add many chunks
        chunks_added = 100
        for _i in range(chunks_added):
            buffer.append(f"chunk{_i}")

        # Should handle the load
        assert buffer.total_length == sum(
            len(f"chunk{_i}") for _i in range(chunks_added)
        )
        assert buffer.stored_length <= buffer.max_size

        # Content should end with most recent chunks
        content = buffer.get_content()
        assert "chunk99" in content
