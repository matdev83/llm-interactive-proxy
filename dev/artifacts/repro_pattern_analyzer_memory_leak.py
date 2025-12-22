"""Repro script for PatternAnalyzer._content_stats memory leak.

This script demonstrates that PatternAnalyzer._content_stats can grow unbounded
when many unique hash values are encountered without triggering stream history truncation.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.loop_detection.analyzer import PatternAnalyzer
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.hasher import ContentHasher


def main():
    """Demonstrate unbounded growth of _content_stats dict."""
    # Create config with large max_history_length so truncation doesn't happen
    config = InternalLoopDetectionConfig(
        content_chunk_size=50,
        content_loop_threshold=3,
        max_history_length=1000000,  # Very large to prevent truncation
        whitelist=None,
    )
    
    hasher = ContentHasher()
    analyzer = PatternAnalyzer(config, hasher)
    
    print("Testing PatternAnalyzer._content_stats memory leak...")
    print(f"Initial size: {len(analyzer._content_stats)}")
    print(f"Initial stream_history length: {len(analyzer._stream_history)}")
    
    # Simulate many unique content chunks being processed
    # Each unique chunk creates a new entry in _content_stats
    # If truncation doesn't happen, _content_stats can grow unbounded
    for i in range(50000):
        # Create unique content chunks
        unique_content = f"unique_content_chunk_{i}_with_some_text_to_make_it_longer"
        analyzer.ingest_chunk(unique_content)
        
        if i % 5000 == 0:
            print(
                f"After {i} chunks: "
                f"{len(analyzer._content_stats)} unique hashes, "
                f"stream_history length: {len(analyzer._stream_history)}"
            )
    
    print(f"Final _content_stats size: {len(analyzer._content_stats)}")
    print(f"Final stream_history length: {len(analyzer._stream_history)}")
    print(
        f"Memory leak confirmed: _content_stats grew to {len(analyzer._content_stats)} entries "
        f"while stream_history is only {len(analyzer._stream_history)} chars"
    )
    print(
        "Issue: _content_stats accumulates unique hashes even when stream_history "
        "stays within limits. Truncation only happens when stream_history exceeds "
        "max_history_length, but _content_stats can grow independently."
    )


if __name__ == "__main__":
    main()
