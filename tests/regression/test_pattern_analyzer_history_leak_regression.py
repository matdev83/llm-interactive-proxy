"""Regression test for PatternAnalyzer history memory leak fix.

This test verifies that PatternAnalyzer.history is truncated when it exceeds
the maximum size to prevent unbounded memory growth.
"""

import pytest
from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.event import LoopDetectionEvent
from src.loop_detection.hasher import ContentHasher


class TestPatternAnalyzerHistoryLeakRegression:
    """Regression tests for PatternAnalyzer history leak fix."""

    @pytest.fixture
    def analyzer(self) -> PatternAnalyzer:
        """Create PatternAnalyzer for testing."""
        config = InternalLoopDetectionConfig(
            enabled=True,
            content_chunk_size=80,
            content_loop_threshold=6,
            max_history_length=4096,
        )
        hasher = ContentHasher()
        return PatternAnalyzer(config, hasher)

    def test_history_truncated_when_exceeds_limit(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that history is truncated when it exceeds the limit."""
        # Max event history is 100 (hardcoded in _truncate_event_history_if_needed)
        max_event_history = 100

        # Add more than the limit
        num_events = max_event_history + 50
        for _i in range(num_events):
            event = LoopDetectionEvent(
                pattern="A" * 80,
                pattern_length=80,
                repetition_count=6,
                total_length=480,
                confidence=1.0,
                buffer_content="A" * 800,
                timestamp=0.0,
            )
            analyzer.history.append(event)
            # Call truncation manually to test it
            analyzer._truncate_event_history_if_needed()

        # History should be truncated to max_event_history
        assert len(analyzer.history) <= max_event_history, (
            f"History ({len(analyzer.history)}) should be <= {max_event_history}. "
            "Truncation is not working."
        )

    def test_history_not_truncated_below_limit(self, analyzer: PatternAnalyzer) -> None:
        """Test that history is not truncated when below the limit."""
        num_events = 50  # Below limit

        for _i in range(num_events):
            event = LoopDetectionEvent(
                pattern="A" * 80,
                pattern_length=80,
                repetition_count=6,
                total_length=480,
                confidence=1.0,
                buffer_content="A" * 800,
                timestamp=0.0,
            )
            analyzer.history.append(event)
            analyzer._truncate_event_history_if_needed()

        # History should not be truncated
        assert (
            len(analyzer.history) == num_events
        ), f"History should have {num_events} events, got {len(analyzer.history)}"

    def test_history_oldest_events_removed(self, analyzer: PatternAnalyzer) -> None:
        """Test that oldest events are removed when truncating."""
        max_event_history = 100
        num_events = max_event_history + 20

        # Add events with unique patterns
        for i in range(num_events):
            event = LoopDetectionEvent(
                pattern=f"Pattern{i}",
                pattern_length=80,
                repetition_count=6,
                total_length=480,
                confidence=1.0,
                buffer_content=f"Content{i}",
                timestamp=float(i),
            )
            analyzer.history.append(event)
            analyzer._truncate_event_history_if_needed()

        # Should have exactly max_event_history events
        assert (
            len(analyzer.history) == max_event_history
        ), f"Expected {max_event_history} events, got {len(analyzer.history)}"

        # Oldest events (0-19) should be removed, newest events (100-119) should remain
        # Since we truncate by removing oldest, events 20-119 should remain
        # But we added 120 events total, so after truncation we should have events 20-119
        # Actually, let's check that the first event is not one of the oldest
        if analyzer.history:
            first_event = analyzer.history[0]
            # The first event should be from later in the sequence (not Pattern0)
            assert (
                first_event.pattern != "Pattern0"
            ), "Oldest events should be removed during truncation"

    def test_history_truncation_called_on_detection(
        self, analyzer: PatternAnalyzer
    ) -> None:
        """Test that truncation is called when events are detected."""
        # This test verifies that analyze_pending_stream calls truncation
        # We'll trigger detections by analyzing content with repeating patterns
        repeating_chunk = "A" * 80

        # Build up stream history to trigger detections
        for i in range(200):
            analyzer.ingest_chunk(repeating_chunk)
            if i >= 10:  # Need some history first
                buffer_content = repeating_chunk * 20
                analyzer.analyze_pending_stream(buffer_content)

        # History should be bounded
        max_event_history = 100
        assert len(analyzer.history) <= max_event_history, (
            f"History ({len(analyzer.history)}) should be <= {max_event_history}. "
            "Truncation should be called on detection."
        )
