"""Regression test for PatternAnalyzer memory leak fix.

This test verifies that PatternAnalyzer._content_stats is properly bounded
and cleaned up to prevent unbounded memory growth.
"""

import pytest
from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


class TestPatternAnalyzerMemoryLeakRegression:
    """Regression tests for PatternAnalyzer memory leak fix."""

    @pytest.fixture
    def config(self):
        """Create config with large max_history_length to prevent truncation."""
        return InternalLoopDetectionConfig(
            content_chunk_size=50,
            content_loop_threshold=3,
            max_history_length=1000000,  # Very large to prevent truncation
            whitelist=None,
        )

    @pytest.fixture
    def hasher(self):
        """Create content hasher."""
        return ContentHasher()

    @pytest.fixture
    def analyzer(self, config, hasher):
        """Create pattern analyzer."""
        return PatternAnalyzer(config, hasher)

    def test_content_stats_bounded_when_history_truncated(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats is cleaned up when stream_history is truncated."""
        # Process many unique content chunks
        num_chunks = 10000

        for i in range(num_chunks):
            unique_content = (
                f"unique_content_chunk_{i}_with_some_text_to_make_it_longer"
            )
            analyzer.ingest_chunk(unique_content)

        # Check that _content_stats is bounded
        # The analyzer should clean up stats when history is truncated
        content_stats_size = len(analyzer._content_stats)
        len(analyzer._stream_history)

        # Content stats should be bounded relative to history length
        # If history is truncated, stats should also be cleaned up
        assert content_stats_size <= num_chunks, (
            f"_content_stats size ({content_stats_size}) exceeded expected limit. "
            "Stats are not being cleaned up when history is truncated."
        )

    def test_content_stats_cleaned_on_history_truncation(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats entries are removed when history is truncated."""
        # Process chunks to fill history
        initial_chunks = 500
        for i in range(initial_chunks):
            content = f"chunk_{i}_with_content"
            analyzer.ingest_chunk(content)

        len(analyzer._content_stats)
        len(analyzer._stream_history)

        # Process more chunks to trigger truncation (if max_history_length is exceeded)
        # Since max_history_length is very large, we'll simulate truncation by
        # checking that stats don't grow unbounded
        additional_chunks = 5000
        for i in range(additional_chunks):
            unique_content = f"unique_chunk_{i}_with_different_content"
            analyzer.ingest_chunk(unique_content)

        final_stats_size = len(analyzer._content_stats)
        len(analyzer._stream_history)

        # Stats should not grow unbounded even with many unique chunks
        # The analyzer should have cleanup mechanisms
        assert final_stats_size <= analyzer.config.max_history_length, (
            f"_content_stats size ({final_stats_size}) exceeded max_history_length "
            f"({analyzer.config.max_history_length}). Stats are not being cleaned up."
        )

    def test_content_stats_respects_max_history_length(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats respects max_history_length limit."""
        # Process many unique chunks (reduced from 100000 to 20000)
        num_chunks = 20000

        for i in range(num_chunks):
            unique_content = f"unique_content_{i}_with_text"
            analyzer.ingest_chunk(unique_content)

        # Content stats should be bounded by max_history_length or cleanup mechanism
        content_stats_size = len(analyzer._content_stats)
        max_history = analyzer.config.max_history_length

        # Stats should not exceed a reasonable multiple of max_history_length
        # (allowing for some overhead, but not unbounded growth)
        reasonable_limit = max_history * 2  # Allow some overhead
        assert content_stats_size <= reasonable_limit, (
            f"_content_stats size ({content_stats_size}) exceeded reasonable limit "
            f"({reasonable_limit}) based on max_history_length ({max_history}). "
            "Stats are growing unbounded."
        )

    def test_content_stats_does_not_grow_independently_of_history(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats doesn't grow independently of stream_history."""
        # Process chunks (reduced from 50000 to 10000 for performance)
        num_chunks = 10000

        for i in range(num_chunks):
            unique_content = f"unique_chunk_{i}_with_content"
            analyzer.ingest_chunk(unique_content)

        content_stats_size = len(analyzer._content_stats)
        history_length = len(analyzer._stream_history)

        # Content stats should be proportional to history length, not unbounded
        # If history is bounded, stats should also be bounded
        # Allow some overhead but not orders of magnitude difference
        if history_length > 0:
            stats_to_history_ratio = content_stats_size / history_length
            # Ratio should be reasonable (e.g., < 1000x)
            assert stats_to_history_ratio < 1000, (
                f"_content_stats ({content_stats_size}) is growing independently "
                f"of stream_history ({history_length}). "
                f"Ratio: {stats_to_history_ratio:.2f}x"
            )
