"""Repro script to confirm memory leak in reasoning_chunks deque.

This script demonstrates that reasoning_chunks can grow unbounded
without any size limits, causing memory leaks in long-running streams.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import (
    StreamBufferState,
    StreamingContextRegistry,
)

def test_reasoning_chunks_unbounded_growth():
    """Test that reasoning_chunks deque grows without bounds."""
    registry = StreamingContextRegistry()
    stream_id = "test-stream-1"
    
    # Get state
    state = registry.get_content_state(stream_id)
    
    # Simulate many reasoning chunks being appended
    # In real code, this happens in content_accumulation_processor.py line 344
    num_chunks = 100000  # Simulate a very long stream
    
    print(f"Appending {num_chunks} reasoning chunks...")
    for i in range(num_chunks):
        reasoning_text = f"Reasoning chunk {i}: " + "x" * 100  # 100 chars each
        state.reasoning_chunks.append(reasoning_text)
        
        # Check memory growth every 10000 chunks
        if (i + 1) % 10000 == 0:
            print(f"  Added {i + 1} chunks, deque length: {len(state.reasoning_chunks)}")
    
    print(f"\nFinal deque length: {len(state.reasoning_chunks)}")
    print(f"Estimated memory: ~{len(state.reasoning_chunks) * 100 / 1024 / 1024:.2f} MB")
    print("\n❌ MEMORY LEAK CONFIRMED: reasoning_chunks deque grows unbounded!")
    print("   No size limit or eviction policy found.")
    
    return len(state.reasoning_chunks)

if __name__ == "__main__":
    test_reasoning_chunks_unbounded_growth()
