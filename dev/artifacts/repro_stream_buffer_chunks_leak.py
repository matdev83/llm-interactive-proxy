"""Repro script to confirm memory leak in StreamBufferState chunks deques.

Issue: chunks, encoded_chunks, and chunk_lengths deques grow unbounded
when streams never complete (e.g., network timeouts, connection failures).

The deques are only cleared when is_done or is_cancellation is True,
but if a stream never sends these flags, the deques will grow indefinitely.
"""

import sys
import tracemalloc
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import (
    StreamBufferState,
    StreamingContextRegistry,
)


def simulate_unbounded_chunk_accumulation():
    """Simulate a stream that never completes, accumulating chunks."""
    registry = StreamingContextRegistry(state_ttl_seconds=300)
    stream_id = "test-stream-never-completes"

    # Start memory tracking
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    # Simulate many chunks being appended without stream completion
    print("Simulating unbounded chunk accumulation...")
    # Add more than the limit to verify it's capped
    for i in range(15000):
        state = registry.get_content_state(stream_id)
        # Simulate appending chunks (like content_accumulation_processor does)
        chunk_text = f"chunk_{i}_" + "x" * 100  # 100 bytes per chunk
        encoded_chunk = chunk_text.encode("utf-8")
        content_length = len(encoded_chunk)

        # Use the new append_content_chunk method that enforces size limits
        state.append_content_chunk(chunk_text, encoded_chunk, content_length)

        if i % 1000 == 0:
            snapshot2 = tracemalloc.take_snapshot()
            top_stats = snapshot2.compare_to(snapshot1, "lineno")
            print(f"\nAfter {i} chunks:")
            print(f"  chunks deque size: {len(state.chunks)}")
            print(f"  encoded_chunks deque size: {len(state.encoded_chunks)}")
            print(f"  chunk_lengths deque size: {len(state.chunk_lengths)}")
            print(f"  byte_length: {state.byte_length}")
            print(f"  Memory growth (top 5):")
            for stat in top_stats[:5]:
                print(f"    {stat}")

    # Final snapshot
    snapshot3 = tracemalloc.take_snapshot()
    top_stats = snapshot3.compare_to(snapshot1, "lineno")
    print(f"\n=== FINAL STATE ===")
    state = registry.get_content_state(stream_id)
    print(f"chunks deque size: {len(state.chunks)}")
    print(f"encoded_chunks deque size: {len(state.encoded_chunks)}")
    print(f"chunk_lengths deque size: {len(state.chunk_lengths)}")
    print(f"byte_length: {state.byte_length}")
    print(f"\nTotal memory growth:")
    for stat in top_stats[:10]:
        print(f"  {stat}")

    # Check if memory grew unbounded
    if len(state.chunks) == 10000:
        print("\n[CONFIRMED] Memory leak - deques grew to 10000 entries")
        print("  The deques will continue growing if more chunks are added")
        return True
    else:
        print("\n[NO LEAK] No leak detected")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("Memory Leak Repro: StreamBufferState chunks deques")
    print("=" * 70)
    leak_confirmed = simulate_unbounded_chunk_accumulation()
    sys.exit(0 if leak_confirmed else 1)
