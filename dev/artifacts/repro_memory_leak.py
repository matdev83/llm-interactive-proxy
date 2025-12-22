#!/usr/bin/env python3
"""
Reproduction script for memory leak in ThoughtSignatureManager.

This script demonstrates that the _by_tool_call secondary index 
can grow unbounded while the primary cache respects its size limit.
"""

import asyncio
import time
import sys
import os
import tracemalloc
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def track_memory():
    """Get current memory usage."""
    if tracemalloc.is_tracing():
        snapshot = tracemalloc.take_snapshot()
        return sum(stat.size for stat in snapshot.statistics("lineno"))
    return 0


async def test_memory_leak():
    """Test for memory leak in ThoughtSignatureManager."""
    
    # Start memory tracking
    tracemalloc.start()
    
    manager = ThoughtSignatureManager(max_cache_size=10, ttl_seconds=1)
    
    print("Testing ThoughtSignatureManager memory leak...")
    print(f"Initial memory: {track_memory() / 1024:.2f} KB")
    
    # Simulate storing signatures like the real code does
    import time
    current_time = time.time()
    
    # Fill cache with unique entries
    for i in range(100):
        session_id = f"session_{i % 5}"  # Rotate through 5 sessions
        tc_id = f"tool_call_{i}"
        sig = f"signature_{i}"
        
        # Simulate the real storage logic from _store_signature_internal
        cache_key = f"{session_id}:{tc_id}"
        manager._cache[cache_key] = (sig, current_time)
        manager._by_tool_call[tc_id] = sig  # This is the problematic part!
        
        # Move to end for LRU
        manager._cache.move_to_end(cache_key)
        
        # Enforce size limit (this should happen automatically)
        if len(manager._cache) > manager._max_cache_size:
            oldest_key, oldest_value = manager._cache.popitem(last=False)
            oldest_sig, _ = oldest_value
            # The flawed cleanup logic
            manager._by_tool_call = {
                k: v
                for k, v in manager._by_tool_call.items()
                if v != oldest_sig
                or any(k2.endswith(f":{k}") for k2 in manager._cache)
            }
        
        if i % 10 == 0:
            print(f"Iteration {i}:")
            print(f"  Primary cache size: {len(manager._cache)}")
            print(f"  Secondary index size: {len(manager._by_tool_call)}")
            print(f"  Memory: {track_memory() / 1024:.2f} KB")
    
    print("\nFinal state:")
    print(f"  Primary cache size: {len(manager._cache)}")
    print(f"  Secondary index size: {len(manager._by_tool_call)}")
    print(f"  Memory: {track_memory() / 1024:.2f} KB")
    
    # The issue: _by_tool_call contains many more entries than _cache
    # This is a memory leak!
    
    if len(manager._by_tool_call) > len(manager._cache) * 2:
        print("\n❌ MEMORY LEAK DETECTED!")
        print(f"Secondary index ({len(manager._by_tool_call)}) is much larger than primary cache ({len(manager._cache)})")
        print(f"Leaked {len(manager._by_tool_call) - len(manager._cache)} entries!")
        return False
    else:
        print("\n✅ No significant memory leak detected")
        return True


if __name__ == "__main__":
    result = asyncio.run(test_memory_leak())
    sys.exit(0 if result else 1)