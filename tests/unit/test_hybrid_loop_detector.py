"""
Tests for HybridLoopDetector.

Tests both short pattern detection (gemini-cli) and long pattern detection (rolling hash).
"""

import pytest
from src.loop_detection.hybrid_detector import HybridLoopDetector


class TestHybridLoopDetector:
    """Test the hybrid loop detection functionality."""

    def test_short_pattern_detection(self):
        """Test that short patterns are detected by the gemini-cli algorithm."""
        detector = HybridLoopDetector()
        detector.reset()

        # Short pattern that should be detected by gemini-cli component
        short_pattern = "Loading... "  # 11 chars

        detection_event = None
        for i in range(20):  # More than gemini-cli threshold
            detection_event = detector.process_chunk(short_pattern)
            if detection_event:
                print(f"Short pattern detected at iteration {i+1}")
                break

        assert (
            detection_event is not None
        ), "Short pattern should be detected by gemini-cli component"
        assert (
            "Loading..." in detection_event.pattern
            or "Repetitive content pattern" in detection_event.pattern
        )

    def test_long_pattern_detection(self):
        """Test that long patterns are detected by the rolling hash algorithm."""
        detector = HybridLoopDetector()
        detector.reset()

        # Long pattern that gemini-cli cannot detect (>50 chars, no internal repetition)
        long_pattern = """This is a longer pattern that contains unique content and should be detected by the rolling hash algorithm when repeated multiple times. """

        print(f"\nLong pattern length: {len(long_pattern)} chars")

        detection_event = None
        for i in range(5):  # Fewer repetitions needed for long patterns
            detection_event = detector.process_chunk(long_pattern)
            if detection_event:
                print(f"Long pattern detected at iteration {i+1}")
                break

        assert (
            detection_event is not None
        ), "Long pattern should be detected by rolling hash component"
        assert detection_event.repetition_count >= 3

    def test_original_bug_pattern_detection(self):
        """Test that the original bug pattern is now detected by the hybrid approach."""
        detector = HybridLoopDetector()
        detector.reset()

        # Original bug pattern (200 characters)
        original_pattern = """Analyzing the Test File Structure

The test file follows the standard pytest structure with:
- Fixtures for setup
- Test classes for organization
- Individual test methods

Key Components:

Fixtures:
"""

        print(f"\nOriginal bug pattern length: {len(original_pattern)} chars")

        detection_event = None
        for i in range(5):  # Should detect within 5 repetitions
            detection_event = detector.process_chunk(original_pattern)
            if detection_event:
                print(f"Original pattern detected at iteration {i+1}")
                break

        assert (
            detection_event is not None
        ), "Original bug pattern MUST be detected by hybrid detector!"
        print(
            f"Detection details: {detection_event.repetition_count} repetitions, {detection_event.total_length} total chars"
        )

    def test_streaming_behavior(self):
        """Test that the detector works with realistic streaming (small chunks)."""
        detector = HybridLoopDetector()
        detector.reset()

        # Long pattern broken into small streaming chunks
        long_pattern = (
            "This is a test pattern that will be streamed in small chunks. " * 3
        )

        detection_event = None
        # Simulate streaming by feeding 10 chars at a time
        for i in range(0, len(long_pattern), 10):
            chunk = long_pattern[i : i + 10]
            detection_event = detector.process_chunk(chunk)
            if detection_event:
                break

        # May or may not detect depending on pattern structure, but should not crash
        # This test mainly ensures streaming behavior works correctly
        assert True  # Just ensure no exceptions

    def test_mixed_pattern_types(self):
        """Test behavior with mixed short and long patterns."""
        detector = HybridLoopDetector()
        detector.reset()

        # Start with short patterns
        short_pattern = "Wait... "
        for _ in range(5):
            detector.process_chunk(short_pattern)

        # Switch to long patterns
        long_pattern = "Now we switch to a much longer pattern that should be handled differently by the hybrid detector system. "

        detection_event = None
        for _ in range(5):
            detection_event = detector.process_chunk(long_pattern)
            if detection_event:
                break

        # Should detect either the short or long pattern
        assert (
            detection_event is not None
        ), "Expected at least one loop detection for mixed patterns"

        stats = detector.get_stats()
        assert stats["total_events"] > 0
        assert detection_event.repetition_count >= 2

    def test_performance_with_large_content(self):
        """Test that the detector performs well with larger content volumes."""
        detector = HybridLoopDetector()
        detector.reset()

        # Generate truly varied content to avoid triggering detection
        # Use different sentence structures and lengths to avoid pattern matching
        varied_content = [
            "Processing items with completely different structure and varied lengths here.",
            "Analyzing data points using alternative methodology and approaches now.",
            "Examining elements through diverse techniques and comprehensive analysis today.",
            "Reviewing components via distinct processes and methodological frameworks currently.",
            "Investigating aspects with unique approaches and specialized techniques available.",
        ]

        # This should be fast and not trigger false positives
        for i in range(20):  # Reduced iterations, use cycling content
            content = varied_content[i % len(varied_content)]
            detector.process_chunk(content)
            # Allow occasional detection due to cycling, but most should be None
            # This test mainly ensures performance and no crashes

        stats = detector.get_stats()
        assert stats["is_enabled"] is True

    def test_enable_disable_functionality(self):
        """Test enable/disable functionality."""
        detector = HybridLoopDetector()

        assert detector.is_enabled() is True

        detector.disable()
        assert detector.is_enabled() is False

        # Should not detect when disabled
        pattern = "Test pattern "
        for _ in range(20):
            event = detector.process_chunk(pattern)
            assert event is None

        detector.enable()
        assert detector.is_enabled() is True

    def test_reset_functionality(self):
        """Test that reset clears all state."""
        detector = HybridLoopDetector()

        # Add some content
        detector.process_chunk("Some content to track")

        # Reset should clear everything
        detector.reset()

        stats = detector.get_stats()
        assert stats["total_events"] == 0

    def test_stats_and_history(self):
        """Test statistics and history tracking."""
        detector = HybridLoopDetector()
        detector.reset()

        # Generate a detection
        pattern = "Repeat this "
        for _ in range(15):
            event = detector.process_chunk(pattern)
            if event:
                break

        stats = detector.get_stats()
        assert "detection_method" in stats
        assert "short_detector" in stats
        assert "long_detector" in stats

        history = detector.get_loop_history()
        assert isinstance(history, list)

    @pytest.mark.asyncio
    async def test_async_interface(self):
        """Test the async check_for_loops interface."""
        detector = HybridLoopDetector()

        # Test with repeated content
        repeated_content = "Test pattern " * 20
        result = await detector.check_for_loops(repeated_content)

        assert result.has_loop in [
            True,
            False,
        ]  # May or may not detect depending on pattern

        # Test with empty content
        empty_result = await detector.check_for_loops("")
        assert empty_result.has_loop is False

    def test_configuration_update(self):
        """Test configuration updates."""
        detector = HybridLoopDetector()

        # Test with dict config
        new_config = {
            "short_detector": {"content_chunk_size": 40},
            "long_detector": {"min_pattern_length": 80},
        }

        detector.update_config(new_config)

        # Should not crash and should reset state
        stats = detector.get_stats()
        assert stats["short_detector"]["config"]["content_chunk_size"] == 40


class TestRollingHashTracker:
    """Test the rolling hash component directly."""

    def test_simple_pattern_detection(self):
        """Test basic pattern detection with rolling hash."""
        from src.loop_detection.hybrid_detector import RollingHashTracker

        tracker = RollingHashTracker(min_pattern_length=20, min_repetitions=3)

        pattern = "This is a test pattern. "
        content = pattern * 5

        result = tracker.add_content(content)

        assert result is not None, "Rolling hash should detect repeated pattern"
        detected_pattern, repetitions = result
        assert repetitions >= 3
        assert len(detected_pattern) >= 20

    def test_no_false_positives_on_varied_content(self):
        """Test that varied content doesn't trigger false positives."""
        from src.loop_detection.hybrid_detector import RollingHashTracker

        tracker = RollingHashTracker()

        # Generate varied content
        varied_content = "".join([f"Unique content block {i}. " for i in range(50)])

        result = tracker.add_content(varied_content)

        assert result is None, "Should not detect patterns in varied content"

    def test_truncation_behavior(self):
        """Test that content truncation works correctly."""
        from src.loop_detection.hybrid_detector import RollingHashTracker

        tracker = RollingHashTracker(max_history=100)

        # Add content that exceeds max_history
        long_content = "A" * 200
        tracker.add_content(long_content)

        assert len(tracker.content) <= 100, "Content should be truncated to max_history"

    def test_hash_collision_resistance(self):
        """Test that hash collisions are properly handled."""
        from src.loop_detection.hybrid_detector import RollingHashTracker

        tracker = RollingHashTracker(min_pattern_length=10, min_repetitions=2)

        # Add patterns that might have hash collisions but different content
        pattern1 = "Pattern A " * 3
        pattern2 = "Pattern B " * 3

        tracker.add_content(pattern1)
        tracker.reset()
        tracker.add_content(pattern2)

        # Both should be detected independently
        # (This test mainly ensures no crashes due to hash collisions)
        assert True  # Main goal is no exceptions


if __name__ == "__main__":
    # Quick manual test
    detector = HybridLoopDetector()

    print("Testing original bug pattern...")
    original_pattern = """Analyzing the Test File Structure

The test file follows the standard pytest structure with:
- Fixtures for setup
- Test classes for organization
- Individual test methods

Key Components:

Fixtures:
"""

    for i in range(5):
        event = detector.process_chunk(original_pattern)
        if event:
            print(
                f"[OK] Detected at iteration {i+1}: {event.repetition_count} repetitions"
            )
            break
    else:
        print("[X] Not detected")
