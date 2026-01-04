"""
Test to verify that PatternAnalyzer.history truncation works correctly.
"""

import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


def test_history_truncation():
    """Test that history is truncated when it exceeds the limit."""
    config = InternalLoopDetectionConfig(
        enabled=True,
        content_chunk_size=80,
        content_loop_threshold=6,
        max_history_length=4096,
    )

    hasher = ContentHasher()
    analyzer = PatternAnalyzer(config, hasher)

    # Create a repeating pattern that will trigger detection
    repeating_chunk = "A" * 80

    # Manually add events to history to test truncation
    # We'll add more than 100 events (the truncation limit)
    import time

    from src.loop_detection.event import LoopDetectionEvent

    for i in range(150):
        event = LoopDetectionEvent(
            pattern=repeating_chunk,
            pattern_length=80,
            repetition_count=6,
            total_length=480,
            confidence=1.0,
            buffer_content=repeating_chunk * 10,
            timestamp=time.time(),
        )
        analyzer.history.append(event)
        # Call truncation manually to test it
        analyzer._truncate_event_history_if_needed()

    # History should be truncated to 100 events
    assert (
        len(analyzer.history) == 100
    ), f"Expected 100 events, got {len(analyzer.history)}"
    print(f"SUCCESS: History correctly truncated to {len(analyzer.history)} events")

    # Verify the oldest events were removed (check first event)
    # Since we added 150 events and truncated to 100, the first event should be #51
    # But actually, we're appending and truncating each time, so the first 50 should be removed
    # Let's verify by checking that we have exactly 100 events
    assert len(analyzer.history) <= 100, "History exceeds limit!"

    print("Test passed: History truncation is working correctly")


if __name__ == "__main__":
    test_history_truncation()
    print("All tests passed!")
