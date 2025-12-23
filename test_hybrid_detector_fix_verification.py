"""
Memory leak repro script for HybridLoopDetector (verification).

This script verifies that the _loop_events list no longer grows unbounded.
"""

import sys
import os

# Ensure we're in the right place
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from loop_detection.hybrid_detector import HybridLoopDetector

def test_bounded_growth():
    """Test that shows _loop_events list is now bounded."""

    # Initialize with minimal config to disable short detector
    # Use content that triggers the long detector
    detector = HybridLoopDetector(
        short_detector_config={'content_chunk_size': 1, 'content_loop_threshold': 10000, 'max_history_length': 1},
        long_detector_config={'min_pattern_length': 5, 'max_pattern_length': 100, 'min_repetitions': 2, 'max_history': 5000},
    )

    print(f"Initial state:")
    print(f"  Event count: {len(detector.get_loop_history())}")

    # Simulate many content chunks
    # The long detector adds events to _loop_events
    for i in range(10000):
        # Generate content that won't exactly trigger loop detection but generates some events
        chunk = "test-pattern-" + str(i % 50) + " "

        detector.process_chunk(chunk)

        if i % 1000 == 0:
            event_count = len(detector.get_loop_history())
            print(f"After {i} chunks: Event count = {event_count}")

    # Final stats
    final_event_count = len(detector.get_loop_history())

    print(f"\nFinal state:")
    print(f"  Event count: {final_event_count}")

    # Check for unbounded growth - should be bounded now by _max_event_history (100)
    if final_event_count > 150:
        print("\n*** MEMORY LEAK STILL EXISTS! ***")
        print(f"The _loop_events list grew to {final_event_count} entries.")
        print("The truncation is not working as expected.")
        return False
    else:
        print("\n*** FIX VERIFIED! ***")
        print(f"The _loop_events list is bounded at {final_event_count} entries.")
        print("Automatic truncation is working correctly.")
        return True

if __name__ == "__main__":
    success = test_bounded_growth()
    sys.exit(0 if success else 1)
