#!/usr/bin/env python3
"""
Reproduction script for ThinkTagsProcessor memory leak.

This script simulates the memory leak by creating multiple streaming sessions
with unique session IDs, similar to how the actual application works.
"""

import gc
import os
import sys
import tracemalloc
import asyncio
from typing import Any
from unittest.mock import Mock

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
src_path = os.path.join(project_root, 'src')

# Add both project root and src to PYTHONPATH
sys.path.insert(0, project_root)
sys.path.insert(0, src_path)

print(f"Project root: {project_root}")
print(f"Src path: {src_path}")
print(f"Path exists: {os.path.exists(src_path)}")
print(f"Python path: {sys.path[:3]}...")

from src.core.ports.streaming_processors import ThinkTagsProcessor
from src.core.ports.streaming_contracts import StreamingContent

def measure_memory_usage():
    """Get current memory usage in MB."""
    # Force garbage collection
    gc.collect()
    
    # Get memory usage from tracemalloc
    current, peak = tracemalloc.get_traced_memory()
    return current / 1024 / 1024  # Convert to MB

async def simulate_streaming_session(processor: ThinkTagsProcessor, session_id: str):
    """Simulate a streaming session that triggers think tags processing."""
    # Create a mock streaming content with some content
    content = StreamingContent(
        content="Here is some content that needs processing",
        stream_id=session_id,
        metadata={}
    )
    
    # Process the content
    await processor.process(content)
    
    # Add a [DONE] marker to trigger cleanup (but _reasoning_extracted won't be cleaned)
    done_content = StreamingContent(
        content="[DONE]",
        stream_id=session_id,
        metadata={}
    )
    await processor.process(done_content)

async def main():
    """Main reproduction script."""
    print("ThinkTagsProcessor Memory Leak Reproduction")
    print("=" * 50)
    
    # Start memory tracing
    tracemalloc.start()
    
    initial_memory = measure_memory_usage()
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Create a single processor instance (simulating the bug)
    processor = ThinkTagsProcessor(enabled=True)
    
    # Simulate multiple streaming sessions (this is where the leak occurs)
    num_sessions = 1000
    print(f"\nSimulating {num_sessions} streaming sessions...")
    
    for i in range(num_sessions):
        session_id = f"session_{i}"
        await simulate_streaming_session(processor, session_id)
        
        if (i + 1) % 100 == 0:
            current_memory = measure_memory_usage()
            memory_growth = current_memory - initial_memory
            print(f"  Sessions processed: {i + 1}, Memory growth: {memory_growth:.2f} MB")
            print(f"  _reasoning_extracted size: {len(processor._reasoning_extracted)} entries")
            print(f"  _streaming_buffers size: {len(processor._streaming_buffers)} entries")
            print(f"  _stream_states size: {len(processor._stream_states)} entries")
    
    final_memory = measure_memory_usage()
    total_growth = final_memory - initial_memory
    
    print(f"\n" + "=" * 50)
    print("RESULTS:")
    print(f"Initial memory: {initial_memory:.2f} MB")
    print(f"Final memory: {final_memory:.2f} MB")
    print(f"Total memory growth: {total_growth:.2f} MB")
    print(f"Growth per session: {total_growth / num_sessions:.4f} MB")
    
    print(f"\nDictionary sizes after {num_sessions} sessions:")
    print(f"  _reasoning_extracted: {len(processor._reasoning_extracted)} entries")
    print(f"  _streaming_buffers: {len(processor._streaming_buffers)} entries") 
    print(f"  _stream_states: {len(processor._stream_states)} entries")
    
    # The bug: _reasoning_extracted grows without bound because it's never cleaned up
    # in _cleanup_session_state() method (line 642 explicitly keeps it)
    
    if len(processor._reasoning_extracted) > 0:
        print(f"\n*** MEMORY LEAK CONFIRMED! ***")
        print(f"The _reasoning_extracted dictionary contains {len(processor._reasoning_extracted)} stale entries")
        print(f"that will never be cleaned up, causing unbounded memory growth.")
        return True
    else:
        print(f"\n*** No memory leak detected ***")
        return False

if __name__ == "__main__":
    leak_detected = asyncio.run(main())
    sys.exit(1 if leak_detected else 0)