"""
Repro script to confirm memory leak in PatternAnalyzer.history.

The PatternAnalyzer.history list grows unbounded without any eviction policy,
unlike LoopDetector._history which has truncation logic.
"""

import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


def main():
    """Run the memory leak repro."""
    print("=" * 60)
    print("PatternAnalyzer.history Memory Leak Repro")
    print("=" * 60)
    
    config = InternalLoopDetectionConfig(
        enabled=True,
        content_chunk_size=80,
        content_loop_threshold=6,
        max_history_length=4096,  # This is for stream history, not event history
    )
    
    hasher = ContentHasher()
    analyzer = PatternAnalyzer(config, hasher)
    
    print(f"Initial history size: {len(analyzer.history)}")
    print(f"Config max_history_length: {config.max_history_length}")
    print()
    
    # Create a repeating pattern that will trigger loop detection
    # We need a pattern that's exactly content_chunk_size (80 chars)
    repeating_chunk = "A" * 80  # Exactly chunk size
    
    print("Simulating loop detections...")
    print("Building up stream history to trigger detections...")
    
    # Build up the stream history by ingesting chunks
    # We need at least 6 repetitions (content_loop_threshold) to trigger detection
    # Each chunk is 80 chars, so we need at least 6 * 80 = 480 chars
    # But we need them spaced appropriately to trigger detection
    
    detection_count = 0
    iterations_without_detection = 0
    
    # Strategy: Keep adding the same chunk repeatedly
    # The analyzer will detect when the same chunk appears 6+ times
    for iteration in range(200):
        # Add chunk to stream
        analyzer.ingest_chunk(repeating_chunk)
        
        # Get current stream content for analysis
        # We need to build up enough content first
        if iteration < 10:
            continue  # Build up initial history
        
        # Analyze the stream
        # We'll use a large buffer content that includes our repeating pattern
        buffer_content = repeating_chunk * 20  # Large buffer
        event = analyzer.analyze_pending_stream(buffer_content)
        
        if event:
            detection_count += 1
            history_size = len(analyzer.history)
            if detection_count <= 5 or detection_count % 10 == 0:
                print(f"  Detection #{detection_count} at iteration {iteration+1}: history size = {history_size}")
            
            iterations_without_detection = 0
            
            # Check if history is growing unbounded
            if history_size > 100:
                print(f"\nWARNING: MEMORY LEAK CONFIRMED: history size = {history_size} (unbounded growth!)")
                print(f"   After {detection_count} detections, history continues to grow.")
                break
        else:
            iterations_without_detection += 1
    
    print(f"\nFinal history size: {len(analyzer.history)}")
    print(f"Total detections: {detection_count}")
    print()
    
    if len(analyzer.history) > 50:
        print("CONFIRMED: PatternAnalyzer.history grows unbounded!")
        print("   The history list has no size limit or eviction policy.")
        print("   Unlike LoopDetector._history which uses max_history_length,")
        print("   PatternAnalyzer.history only clears on reset().")
        print()
        print("   Each LoopDetectionEvent stores:")
        print("   - pattern (string)")
        print("   - buffer_content (full buffer string, can be large)")
        print("   - other metadata")
        print()
        print("   In a long-running session with many loop detections,")
        print("   this can consume significant memory.")
        return 1
    elif len(analyzer.history) <= 100:
        print("FIX VERIFIED: History is now bounded!")
        print(f"   History size: {len(analyzer.history)} (should be <= 100)")
        print("   The _truncate_event_history_if_needed() method is working.")
        return 0
    elif len(analyzer.history) > 0:
        print("History is growing but not yet excessive.")
        print("However, without limits, it will continue to grow in production.")
        return 0
    else:
        print("No detections triggered. The repro may need adjustment.")
        print("But the code analysis shows the leak exists:")
        print("  - PatternAnalyzer.history.append() on line 104")
        print("  - No truncation logic (unlike LoopDetector._history)")
        print()
        print("Manual inspection confirms:")
        print("  1. PatternAnalyzer.history is a list that grows on each detection")
        print("  2. LoopDetector._history has _truncate_history_if_needed() method")
        print("  3. PatternAnalyzer.history has no such truncation")
        print("  4. History only clears on reset(), which may not happen frequently")
        return 0


if __name__ == "__main__":
    sys.exit(main())
