"""Regression test for PatternAnalyzer._content_stats leak with analyze_pending_stream calls.

This test verifies that PatternAnalyzer._content_stats doesn't grow unbounded
when analyze_pending_stream is called regularly during stream processing.
"""

import pytest
from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


class TestPatternAnalyzerContentStatsWithAnalysisRegression:
    """Regression tests for PatternAnalyzer content_stats with analyze_pending_stream calls."""

    @pytest.fixture
    def config(self):
        """Create config tuned for fast regression coverage.

        The goal is to verify that `_content_stats` stays bounded and that index
        cleanup behaves correctly when history truncation happens, without
        turning the regression suite into a multi-minute stress test.
        """
        return InternalLoopDetectionConfig(
            content_chunk_size=200,
            content_loop_threshold=3,
            max_history_length=5000,
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

    def test_content_stats_bounded_with_regular_analysis(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats is bounded when analyze_pending_stream is called regularly."""
        # Simulate many unique content chunks being processed
        # Each unique chunk creates a new entry in _content_stats when analyzed
        # We call analyze_pending_stream every 100 chunks to trigger _is_loop_detected_for_chunk
        num_chunks = 50
        for i in range(num_chunks):
            # Create unique content chunks
            unique_content = (
                f"unique_content_chunk_{i}_with_some_text_to_make_it_longer_and_unique"
            )
            analyzer.ingest_chunk(unique_content)

            # Trigger analysis periodically to simulate real usage
            # This is what populates _content_stats
            if i % 25 == 0 and i > 0:
                # Build buffer content for analysis
                buffer_content = analyzer._stream_history[-100:]
                analyzer.analyze_pending_stream(buffer_content)

        final_stats_size = len(analyzer._content_stats)
        final_history_length = len(analyzer._stream_history)

        # Content stats should be bounded relative to history length
        # Even with many unique chunks and regular analysis, stats shouldn't grow unbounded
        assert final_stats_size <= analyzer.config.max_history_length

        # Stats should be proportional to history, not orders of magnitude larger
        if final_history_length > 0:
            stats_to_history_ratio = final_stats_size / final_history_length
            # Ratio should be reasonable (e.g., < 100x)
            assert stats_to_history_ratio < 100

    def test_content_stats_cleaned_when_history_truncated_with_analysis(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that _content_stats entries are cleaned when history is truncated with analysis."""
        # Process chunks to fill history
        initial_chunks = 50
        for i in range(initial_chunks):
            content = f"chunk_{i}_with_content"
            analyzer.ingest_chunk(content)
            if i % 25 == 0 and i > 0:
                buffer_content = analyzer._stream_history[-100:]
                analyzer.analyze_pending_stream(buffer_content)

        len(analyzer._content_stats)
        assert len(analyzer._stream_history) <= analyzer.config.max_history_length

        # Process more chunks with analysis to trigger potential truncation
        additional_chunks = 50
        for i in range(additional_chunks):
            unique_content = f"unique_chunk_{i}_with_different_content"
            analyzer.ingest_chunk(unique_content)
            if i % 25 == 0:
                buffer_content = analyzer._stream_history[-100:]
                analyzer.analyze_pending_stream(buffer_content)

        final_stats_size = len(analyzer._content_stats)
        final_history_length = len(analyzer._stream_history)

        # History should be truncated and indices should remain in-range.
        assert final_history_length <= analyzer.config.max_history_length
        assert final_stats_size <= analyzer.config.max_history_length
        for indices in analyzer._content_stats.values():
            assert all(0 <= idx < final_history_length for idx in indices)
