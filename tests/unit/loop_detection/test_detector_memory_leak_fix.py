#!/usr/bin/env python3
"""
Test for memory leak fix in LoopDetector._history list.

This test verifies that _history list is properly bounded and doesn't grow
unbounded, preventing memory leaks.
"""

import time
from unittest.mock import patch

from loop_detection.config import InternalLoopDetectionConfig
from loop_detection.detector import LoopDetector
from loop_detection.event import LoopDetectionEvent


class TestLoopDetectorMemoryLeakFix:
    """Test suite for LoopDetector memory leak fixes."""

    def test_history_truncation_on_process_chunk(self) -> None:
        """Test that _history is truncated during process_chunk operations."""
        # Configure with very small history limit
        max_history = 5
        config = InternalLoopDetectionConfig(
            enabled=True,
            max_history_length=max_history,
            content_chunk_size=10,
            content_loop_threshold=2,
        )
        detector = LoopDetector(config)

        # Manually add events to exceed limit
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            for i in range(max_history + 10):
                event = LoopDetectionEvent(
                    pattern=f"pattern_{i}",
                    pattern_length=20,
                    repetition_count=3,
                    total_length=60,
                    confidence=0.9,
                    buffer_content="test content",
                    timestamp=time.time() + i,
                )
                detector._history.append(event)
                detector._truncate_history_if_needed()

        # Should not exceed limit
        assert len(detector._history) <= max_history
        assert len(detector._history) == max_history  # Should be exactly at limit

        # Should contain most recent entries
        assert detector._history[0].pattern == "pattern_10"
        assert detector._history[-1].pattern == f"pattern_{max_history + 9}"

    def test_history_truncation_on_check_for_loops(self) -> None:
        """Test that _history is truncated during check_for_loops operations."""
        import asyncio

        max_history = 3
        config = InternalLoopDetectionConfig(
            enabled=True,
            max_history_length=max_history,
            content_chunk_size=5,
            content_loop_threshold=2,
        )
        detector = LoopDetector(config)

        # Simulate many loop detections via check_for_loops
        repetitive_content = "repeat " * 10

        base_time = 1000.0

        async def run_checks():
            with patch("time.time", return_value=base_time):
                for i in range(10):
                    # Create manual events to simulate detection
                    event = LoopDetectionEvent(
                        pattern=f"check_pattern_{i}",
                        pattern_length=15,
                        repetition_count=2,
                        total_length=30,
                        confidence=0.8,
                        buffer_content=repetitive_content,
                        timestamp=time.time() + i,
                    )

                    # This simulates what check_for_loops does
                    detector._history.append(event)
                    detector._truncate_history_if_needed()

        asyncio.run(run_checks())

        # Should not exceed limit
        assert len(detector._history) <= max_history

        # Should contain most recent entries
        assert detector._history[0].pattern == "check_pattern_7"
        assert detector._history[-1].pattern == "check_pattern_9"

    def test_history_no_truncation_when_under_limit(self) -> None:
        """Test that _history is not truncated when under the limit."""
        max_history = 10
        config = InternalLoopDetectionConfig(
            enabled=True,
            max_history_length=max_history,
        )
        detector = LoopDetector(config)

        # Add fewer events than limit
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            for i in range(max_history - 2):
                event = LoopDetectionEvent(
                    pattern=f"pattern_{i}",
                    pattern_length=20,
                    repetition_count=3,
                    total_length=60,
                    confidence=0.9,
                    buffer_content="test content",
                    timestamp=time.time() + i,
                )
                detector._history.append(event)
                detector._truncate_history_if_needed()

        # Should have all events
        assert len(detector._history) == max_history - 2
        assert detector._history[0].pattern == "pattern_0"
        assert detector._history[-1].pattern == f"pattern_{max_history - 3}"

    def test_history_preserves_most_recent_entries(self) -> None:
        """Test that truncation preserves the most recent entries."""
        max_history = 5
        config = InternalLoopDetectionConfig(
            enabled=True,
            max_history_length=max_history,
        )
        detector = LoopDetector(config)

        # Add events with sequential timestamps
        events = []
        for i in range(15):
            event = LoopDetectionEvent(
                pattern=f"sequential_{i:02d}",
                pattern_length=25,
                repetition_count=4,
                total_length=100,
                confidence=0.95,
                buffer_content="sequential test content",
                timestamp=i,  # Simple sequential timestamps
            )
            events.append(event)
            detector._history.append(event)
            detector._truncate_history_if_needed()

        # Should have exactly max_history entries
        assert len(detector._history) == max_history

        # Should contain the last max_history events
        expected_patterns = [f"sequential_{i:02d}" for i in range(10, 15)]
        actual_patterns = [event.pattern for event in detector._history]

        assert actual_patterns == expected_patterns

    def test_history_truncation_logs_debug_message(self, caplog) -> None:
        """Test that history truncation logs debug messages."""
        import logging

        # Enable debug logging to capture debug messages
        with caplog.at_level(logging.DEBUG, logger="loop_detection.detector"):
            max_history = 2
            config = InternalLoopDetectionConfig(
                enabled=True,
                max_history_length=max_history,
            )
            detector = LoopDetector(config)

            # Add events to trigger truncation
            base_time = 1000.0
            with patch("time.time", return_value=base_time):
                for i in range(5):
                    event = LoopDetectionEvent(
                        pattern=f"debug_{i}",
                        pattern_length=10,
                        repetition_count=2,
                        total_length=20,
                        confidence=0.8,
                        buffer_content="debug content",
                        timestamp=time.time() + i,
                    )
                    detector._history.append(event)
                    detector._truncate_history_if_needed()

            # Check for debug log message
            assert "Truncated loop detection history" in caplog.text
            assert "removed 1 oldest entries" in caplog.text
            assert "keeping 2" in caplog.text

    def test_get_loop_history_returns_copy(self) -> None:
        """Test that get_loop_history returns a copy, not the original list."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config)

        # Add some events
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            for i in range(3):
                event = LoopDetectionEvent(
                    pattern=f"copy_test_{i}",
                    pattern_length=15,
                    repetition_count=2,
                    total_length=30,
                    confidence=0.7,
                    buffer_content="copy test content",
                    timestamp=time.time() + i,
                )
                detector._history.append(event)

        # Get history and modify it
        history_copy = detector.get_loop_history()
        history_copy.clear()

        # Original should be unchanged
        assert len(detector._history) == 3
        assert detector._history[0].pattern == "copy_test_0"
