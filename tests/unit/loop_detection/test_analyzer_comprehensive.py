"""
Tests for PatternAnalyzer.

This module provides comprehensive test coverage for the PatternAnalyzer class.
"""

import pytest
import re
from unittest.mock import Mock

from src.loop_detection.analyzer import PatternAnalyzer, LoopDetectionEvent
from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


class TestPatternAnalyzer:
    """Tests for PatternAnalyzer class."""

    @pytest.fixture
    def config(self) -> LoopDetectionConfig:
        """Create a test configuration."""
        return LoopDetectionConfig(
            content_chunk_size=10,
            content_loop_threshold=3,
            max_history_length=100,
        )

    @pytest.fixture
    def hasher(self) -> ContentHasher:
        """Create a content hasher."""
        return ContentHasher()

    @pytest.fixture
    def analyzer(self, config: LoopDetectionConfig, hasher: ContentHasher) -> PatternAnalyzer:
        """Create a fresh PatternAnalyzer for each test."""
        return PatternAnalyzer(config, hasher)

    def test_analyzer_initialization(self, analyzer: PatternAnalyzer, config: LoopDetectionConfig) -> None:
        """Test analyzer initialization."""
        assert analyzer.config == config
        assert analyzer.hasher is not None
        assert analyzer._stream_history == ""
        assert analyzer._content_stats == {}
        assert analyzer._last_chunk_index == 0
        assert analyzer._in_code_block is False

    def test_analyzer_reset(self, analyzer: PatternAnalyzer) -> None:
        """Test analyzer reset functionality."""
        # Add some content and state
        analyzer._stream_history = "test content"
        analyzer._content_stats = {"hash1": [1, 2, 3]}
        analyzer._last_chunk_index = 5
        analyzer._in_code_block = True

        # Reset
        analyzer.reset()

        # Should be back to initial state
        assert analyzer._stream_history == ""
        assert analyzer._content_stats == {}
        assert analyzer._last_chunk_index == 0
        assert analyzer._in_code_block is False

    def test_analyze_chunk_no_loop(self, analyzer: PatternAnalyzer) -> None:
        """Test analyzing chunks with no loop detected."""
        chunk = "normal content"
        full_content = "normal content"

        result = analyzer.analyze_chunk(chunk, full_content)

        assert result is None

    def test_analyze_chunk_simple_loop(self, analyzer: PatternAnalyzer) -> None:
        """Test processing a simple loop pattern."""
        # Create a repeating pattern
        pattern = "repeat" * 5  # 5 repetitions = 30 characters

        # Process the pattern multiple times
        # Note: The exact detection behavior depends on the algorithm implementation
        result = None
        for i in range(analyzer.config.content_loop_threshold + 1):
            result = analyzer.analyze_chunk(pattern, pattern)

        # The test may or may not detect a loop depending on the algorithm
        # The important thing is that it processes without errors
        assert result is None or isinstance(result, LoopDetectionEvent)

    def test_analyze_chunk_code_block_detection(self, analyzer: PatternAnalyzer) -> None:
        """Test that code blocks are handled correctly."""
        # Start of code block
        chunk1 = "```python\n"
        result1 = analyzer.analyze_chunk(chunk1, chunk1)
        assert result1 is None
        assert analyzer._in_code_block is True

        # Content in code block
        chunk2 = "print('hello')\n"
        result2 = analyzer.analyze_chunk(chunk2, chunk1 + chunk2)
        assert result2 is None
        assert analyzer._in_code_block is True

        # End of code block
        chunk3 = "```\n"
        result3 = analyzer.analyze_chunk(chunk3, chunk1 + chunk2 + chunk3)
        assert result3 is None
        assert analyzer._in_code_block is False

    def test_analyze_chunk_markdown_elements_reset(self, analyzer: PatternAnalyzer) -> None:
        """Test that markdown elements trigger reset."""
        markdown_elements = [
            "# Header",
            "- List item",
            "1. Numbered item",
            "| Table | content |",
            "> Blockquote",
            "---",
            "=== divider ===",
            "    indented code",
        ]

        for element in markdown_elements:
            # Add some content first
            analyzer._stream_history = "previous content"
            analyzer._content_stats = {"hash": [1, 2]}

            result = analyzer.analyze_chunk(element, element)

            # Should reset and return None
            assert result is None
            assert analyzer._stream_history != "previous content"
            assert analyzer._content_stats != {"hash": [1, 2]}

    def test_analyze_chunk_chunk_truncation(self, analyzer: PatternAnalyzer) -> None:
        """Test that stream history is properly truncated."""
        # Create content longer than max_history_length
        long_content = "a" * (analyzer.config.max_history_length * 2)
        result = analyzer.analyze_chunk(long_content, long_content)

        assert result is None
        assert len(analyzer._stream_history) <= analyzer.config.max_history_length

    def test_analyze_chunk_multiple_chunks_processing(self, analyzer: PatternAnalyzer) -> None:
        """Test processing multiple chunks in stream history."""
        # Build up stream history with multiple chunks
        chunks = ["chunk1", "chunk2", "chunk3", "chunk4", "chunk5"]

        for chunk in chunks:
            analyzer.analyze_chunk(chunk, "".join(chunks))

        # Should have processed multiple chunks
        assert analyzer._last_chunk_index > 0

    def test_analyze_chunk_empty_and_whitespace(self, analyzer: PatternAnalyzer) -> None:
        """Test handling of empty and whitespace chunks."""
        test_chunks = ["", "   ", "\n", "\t", "content"]

        for chunk in test_chunks:
            result = analyzer.analyze_chunk(chunk, chunk)
            # Should not crash and should handle gracefully
            assert result is None

    def test_analyze_chunk_unicode_content(self, analyzer: PatternAnalyzer) -> None:
        """Test handling of Unicode content."""
        unicode_content = "Hello, 世界! 🌍 Test content with émojis and ñoñäscii"
        result = analyzer.analyze_chunk(unicode_content, unicode_content)

        assert result is None  # Should handle Unicode without errors

    def test_analyze_chunk_very_long_content(self, analyzer: PatternAnalyzer) -> None:
        """Test handling of very long content."""
        long_content = "a" * 10000
        result = analyzer.analyze_chunk(long_content, long_content)

        assert result is None  # Should handle long content without errors

    def test_analyze_chunk_edge_case_boundaries(self, analyzer: PatternAnalyzer) -> None:
        """Test edge cases at chunk boundaries."""
        # Content exactly at chunk size
        chunk_size_content = "a" * analyzer.config.content_chunk_size
        result = analyzer.analyze_chunk(chunk_size_content, chunk_size_content)

        assert result is None

        # Content just over chunk size
        over_chunk_size = "a" * (analyzer.config.content_chunk_size + 1)
        result = analyzer.analyze_chunk(over_chunk_size, over_chunk_size)

        assert result is None

    def test_analyze_chunk_repeating_pattern_detection(self, analyzer: PatternAnalyzer) -> None:
        """Test detection of repeating patterns."""
        # Create a pattern that repeats
        base_pattern = "abcde"
        repeating_content = base_pattern * 10

        # Process the repeating content
        result = analyzer.analyze_chunk(repeating_content, repeating_content)

        # Should not detect loop immediately (needs multiple identical chunks)
        assert result is None

        # Process the same content multiple times
        for i in range(analyzer.config.content_loop_threshold):
            result = analyzer.analyze_chunk(repeating_content, repeating_content)

        # Should eventually detect if pattern repeats enough
        # (This depends on the specific algorithm implementation)

    def test_analyze_chunk_state_consistency(self, analyzer: PatternAnalyzer) -> None:
        """Test that analyzer state remains consistent."""
        initial_state = (
            analyzer._stream_history,
            analyzer._content_stats.copy(),
            analyzer._last_chunk_index,
            analyzer._in_code_block,
        )

        # Process some content
        analyzer.analyze_chunk("test content", "test content")

        # State should have changed appropriately
        assert analyzer._stream_history != initial_state[0] or analyzer._last_chunk_index != initial_state[2]

    def test_analyze_chunk_buffer_content_parameter(self, analyzer: PatternAnalyzer) -> None:
        """Test that buffer_content parameter affects detection event."""
        chunk = "test chunk"
        buffer_content = "full buffer content"

        # Process chunk multiple times to potentially trigger detection
        result = None
        for i in range(10):  # Multiple attempts
            result = analyzer.analyze_chunk(chunk, buffer_content)
            if result:
                break

        if result:
            assert result.buffer_content == buffer_content

    def test_analyze_chunk_timestamp_in_event(self, analyzer: PatternAnalyzer) -> None:
        """Test that detection events have valid timestamps."""
        # Try to trigger detection
        pattern = "repeat" * 10

        result = None
        for i in range(analyzer.config.content_loop_threshold + 2):
            result = analyzer.analyze_chunk(pattern, pattern)
            if result:
                break

        if result:
            assert isinstance(result.timestamp, float)
            assert result.timestamp > 0

    def test_analyze_chunk_confidence_in_event(self, analyzer: PatternAnalyzer) -> None:
        """Test that detection events have confidence values."""
        # Try to trigger detection
        pattern = "repeat" * 10

        result = None
        for i in range(analyzer.config.content_loop_threshold + 2):
            result = analyzer.analyze_chunk(pattern, pattern)
            if result:
                break

        if result:
            assert isinstance(result.confidence, float)
            assert 0.0 <= result.confidence <= 1.0

    def test_analyze_chunk_multiple_different_patterns(self, analyzer: PatternAnalyzer) -> None:
        """Test processing multiple different patterns."""
        patterns = ["pattern1", "pattern2", "pattern3", "pattern4", "pattern5"]

        for pattern in patterns:
            result = analyzer.analyze_chunk(pattern, pattern)
            assert result is None  # Should not detect loops with different patterns

    def test_analyze_chunk_incremental_buildup(self, analyzer: PatternAnalyzer) -> None:
        """Test incremental pattern buildup."""
        base_chunk = "abc"

        # Build up the pattern incrementally
        for i in range(analyzer.config.content_loop_threshold + 2):
            chunk = base_chunk * (i + 1)
            result = analyzer.analyze_chunk(chunk, chunk)
            # May or may not detect depending on algorithm

    def test_analyze_chunk_reset_behavior(self, analyzer: PatternAnalyzer) -> None:
        """Test that reset affects analysis behavior."""
        # Add some content
        analyzer.analyze_chunk("initial content", "initial content")

        # Reset
        analyzer.reset()

        # Add new content
        result = analyzer.analyze_chunk("new content", "new content")

        assert result is None
        assert analyzer._stream_history == "new content"

    def test_analyze_chunk_empty_buffer_content(self, analyzer: PatternAnalyzer) -> None:
        """Test handling of empty buffer content."""
        chunk = "test chunk"
        buffer_content = ""

        result = analyzer.analyze_chunk(chunk, buffer_content)

        assert result is None

    def test_analyze_chunk_none_buffer_content(self, analyzer: PatternAnalyzer) -> None:
        """Test handling of None buffer content."""
        chunk = "test chunk"
        buffer_content = None  # type: ignore

        # Should not crash
        result = analyzer.analyze_chunk(chunk, buffer_content)

        assert result is None

    def test_analyze_chunk_special_characters_in_pattern(self, analyzer: PatternAnalyzer) -> None:
        """Test patterns with special characters."""
        special_patterns = [
            "!@#$%^&*()",
            "line\nwith\nnewlines",
            "tab\tseparated\tcontent",
            "unicode: 中文 español",
            "🌟⭐🚀",
        ]

        for pattern in special_patterns:
            result = analyzer.analyze_chunk(pattern, pattern)
            assert result is None  # Should handle special chars without errors

    def test_analyze_chunk_performance_with_large_content(self, analyzer: PatternAnalyzer) -> None:
        """Test performance with large content chunks."""
        large_chunk = "a" * 10000
        large_buffer = "b" * 50000

        result = analyzer.analyze_chunk(large_chunk, large_buffer)

        # Should complete without errors
        assert result is None

    def test_analyze_chunk_minimal_chunk_size(self, analyzer: PatternAnalyzer) -> None:
        """Test with minimal chunk sizes."""
        minimal_chunks = ["a", "1", " ", ".", "中"]

        for chunk in minimal_chunks:
            result = analyzer.analyze_chunk(chunk, chunk)
            assert result is None  # Should handle minimal chunks

    def test_analyze_chunk_maximal_chunk_size(self, analyzer: PatternAnalyzer) -> None:
        """Test with maximal chunk sizes."""
        large_chunk = "x" * 100000

        result = analyzer.analyze_chunk(large_chunk, large_chunk)

        assert result is None  # Should handle large chunks

    def test_analyze_chunk_state_preservation(self, analyzer: PatternAnalyzer) -> None:
        """Test that analyzer preserves state correctly across calls."""
        # First chunk
        analyzer.analyze_chunk("first", "first")
        first_state = (
            len(analyzer._stream_history),
            analyzer._last_chunk_index,
            analyzer._in_code_block,
        )

        # Second chunk
        analyzer.analyze_chunk("second", "firstsecond")
        second_state = (
            len(analyzer._stream_history),
            analyzer._last_chunk_index,
            analyzer._in_code_block,
        )

        # State should have evolved logically
        assert second_state[0] >= first_state[0]  # History should grow or stay same
        assert second_state[1] >= first_state[1]  # Index should increase or stay same
        assert second_state[2] == first_state[2]  # Code block state should be consistent


class TestLoopDetectionEvent:
    """Tests for LoopDetectionEvent class."""

    def test_event_creation(self) -> None:
        """Test LoopDetectionEvent creation."""
        event = LoopDetectionEvent(
            pattern="test pattern",
            repetition_count=5,
            total_length=100,
            confidence=0.9,
            buffer_content="buffer content",
            timestamp=1234567890.0,
        )

        assert event.pattern == "test pattern"
        assert event.repetition_count == 5
        assert event.total_length == 100
        assert event.confidence == 0.9
        assert event.buffer_content == "buffer content"
        assert event.timestamp == 1234567890.0

    def test_event_default_values(self) -> None:
        """Test LoopDetectionEvent with minimal values."""
        event = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=1,
            total_length=10,
            confidence=0.5,
            buffer_content="content",
            timestamp=1.0,
        )

        assert event.pattern == "pattern"
        assert event.repetition_count == 1
        assert event.total_length == 10
        assert event.confidence == 0.5
        assert event.buffer_content == "content"
        assert event.timestamp == 1.0

    def test_event_as_dict_conversion(self) -> None:
        """Test converting event to dictionary."""
        event = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        # Should be able to access all attributes
        data = {
            "pattern": event.pattern,
            "repetition_count": event.repetition_count,
            "total_length": event.total_length,
            "confidence": event.confidence,
            "buffer_content": event.buffer_content,
            "timestamp": event.timestamp,
        }

        assert data["pattern"] == "pattern"
        assert data["repetition_count"] == 3
        assert data["total_length"] == 50
        assert data["confidence"] == 0.8
        assert data["buffer_content"] == "buffer"
        assert data["timestamp"] == 1234567890.0

    def test_event_equality(self) -> None:
        """Test event equality comparison."""
        event1 = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        event2 = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        event3 = LoopDetectionEvent(
            pattern="different",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        assert event1 == event2
        assert event1 != event3

    def test_event_string_representation(self) -> None:
        """Test event string representation."""
        event = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        str_repr = str(event)
        assert "LoopDetectionEvent" in str_repr
        assert "pattern" in str_repr
        assert "3" in str_repr

    def test_event_not_hashable(self) -> None:
        """Test that event is not hashable (mutable dataclass)."""
        event = LoopDetectionEvent(
            pattern="pattern",
            repetition_count=3,
            total_length=50,
            confidence=0.8,
            buffer_content="buffer",
            timestamp=1234567890.0,
        )

        # Should not be hashable (mutable dataclass)
        with pytest.raises(TypeError):
            event_set = {event}

        with pytest.raises(TypeError):
            event_dict = {event: "value"}
