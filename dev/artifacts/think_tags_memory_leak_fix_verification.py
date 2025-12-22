#!/usr/bin/env python3
"""
Verification script for ThinkTagsProcessor memory leak fix.

This script verifies that the memory leak has been fixed by checking
that session state is properly cleaned up.
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
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from src.core.ports.streaming_processors import ThinkTagsProcessor
from src.core.ports.streaming_contracts import StreamingContent

def measure_memory_usage():
    """Get current memory usage in MB."""
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    return current / 1024 / 1024

async def simulate_streaming_session(processor: ThinkTagsProcessor, session_id: str):
    """Simulate a streaming session that triggers think tags processing."""
    # Create a mock streaming content with some content
    content = StreamingContent(
        content="Here is some content that needs processing",
        stream_id=session_id,
        metadata={}
    )
    
    # Process() method calls _ensure_session_state which creates entries
    await processor.process(content)
    
    # Create a proper [DONE] marker to trigger cleanup in _cleanup_session_state
    from src.core.domain.streaming.sentinels import SentinelManager
    done_content = SentinelManager.create_done_chunk()
    done_content.stream_id = session_id
    await processor.process(done_content)

async def main():
    """Main verification script."""
    print("ThinkTagsProcessor Memory Leak Fix Verification")
    print("=" * 50)
    
    # Start memory tracing
    tracemalloc.start()
    
    initial_memory = measure_memory_usage()
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Create a single processor instance
    processor = ThinkTagsProcessor(enabled=True)
    
    # Simulate multiple streaming sessions
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
    
    # After the fix, all dictionaries should be empty after [DONE] processing
    all_empty = (
        len(processor._reasoning_extracted) == 0 and
        len(processor._streaming_buffers) == 0 and
        len(processor._stream_states) == 0
    )
    
    if all_empty:
        print(f"\n*** MEMORY LEAK FIXED! ***")
        print(f"All session state dictionaries are properly cleaned up.")
        print(f"No memory leak detected - fix verified successfully.")
        return True
    else:
        print(f"\n*** MEMORY LEAK NOT FIXED ***")
        print(f"Some session state dictionaries still contain stale entries.")
        return False

if __name__ == "__main__":
    fix_verified = asyncio.run(main())
    sys.exit(0 if fix_verified else 1)