"""
Memory leak repro script for HybridLoopDetector.

This script demonstrates unbounded growth of the _loop_events list.
Run from the root of the repository.
"""

import sys
import os

# Ensure we're in the right place
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from loop_detection.hybrid_detector import HybridLoopDetector

def test_unbounded_growth():
    """Test that shows unbounded growth of _loop_events list."""

    # Initialize with minimal config to disable short detector
    # We'll use content that triggers the long detector which has the issue
    detector = HybridLoopDetector(
        short_detector_config={'content_chunk_size': 1, 'content_loop_threshold': 10000, 'max_history_length': 1},
        long_detector_config={'min_pattern_length': 5, 'max_pattern_length': 100, 'min_repetitions': 2, 'max_history': 5000},
    )

    print(f"Initial state:")
    print(f"  Event count: {len(detector.get_loop_history())}")

    # Simulate many content chunks
    # The long detector adds events to _loop_events but never clears them
    for i in range(10000):
        # Generate content that won't exactly trigger loop detection but will generate some events
        chunk = "test-pattern-" + str(i % 50) + " "

        detector.process_chunk(chunk)

        if i % 1000 == 0:
            event_count = len(detector.get_loop_history())
            print(f"After {i} chunks: Event count = {event_count}")

    # Final stats
    final_event_count = len(detector.get_loop_history())

    print(f"\nFinal state:")
    print(f"  Event count: {final_event_count}")
    print(f"  Event count increase: {final_event_count}")

    # Check for unbounded growth
    if final_event_count > 100:
        print("\n*** MEMORY LEAK CONFIRMED! ***")
        print(f"The _loop_events list grew to {final_event_count} entries without truncation.")
        print("This causes memory leaks in long-running sessions.")
        return False
    else:
        print("\nEvent count appears bounded (no issues detected in this test)")
        return True

if __name__ == "__main__":
    success = test_unbounded_growth()
    sys.exit(0 if success else 1)
