#!/usr/bin/env python3
"""
Isolated test for memory leak in ThoughtSignatureManager.
Tests the specific cleanup logic without importing the full module.
"""

import time
from collections import OrderedDict


def demonstrate_memory_leak():
    """
    Demonstrate the memory leak bug in the cleanup logic.
    
    The issue: When the same tool_call_id appears across multiple sessions,
    the cleanup logic fails to remove it properly from _by_tool_call.
    """
    
    print("=== ThoughtSignatureManager Memory Leak Demo ===\n")
    
    # Simulate the cache structures
    _cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
    _by_tool_call: dict[str, str] = {}
    _max_cache_size = 5
    
    print("1. Adding entries with same tool_call_id across different sessions...\n")
    
    # Add entries where same tc_id appears in multiple sessions
    entries = [
        ("session1:tool_a", "sig1"),
        ("session2:tool_a", "sig2"),  # Same tc_id, different session!
        ("session1:tool_b", "sig3"),
        ("session2:tool_b", "sig4"),  # Same tc_id, different session!
        ("session1:tool_c", "sig5"),
        ("session2:tool_c", "sig6"),  # Same tc_id, different session!
        ("session1:tool_d", "sig7"),  # This will trigger cache eviction
    ]
    
    current_time = time.time()
    
    # Fill cache beyond limit
    for cache_key, sig in entries:
        _cache[cache_key] = (sig, current_time)
        
        # Extract tc_id from cache_key (format: "session_id:tc_id")
        tc_id = cache_key.split(":", 1)[1]
        _by_tool_call[tc_id] = sig  # This overwrites previous sig for same tc_id
        
        print(f"  Added: {cache_key} -> {sig}")
        print(f"    _by_tool_call[{tc_id}] = {sig}")
    
    print(f"\n  Primary cache size: {len(_cache)}")
    print(f"  Secondary index size: {len(_by_tool_call)}")
    
    print("\n2. Simulating cache size enforcement (removing oldest)...\n")
    
    # Enforce size limit (this happens in real code)
    while len(_cache) > _max_cache_size:
        oldest_key, oldest_value = _cache.popitem(last=False)
        oldest_sig, _ = oldest_value
        
        print(f"  Removing oldest: {oldest_key} with signature {oldest_sig}")
        
        # This is the BUGGY cleanup logic from the original code
        _by_tool_call = {
            k: v
            for k, v in _by_tool_call.items()
            if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in _cache)
        }
        
        print(f"    After cleanup:")
        print(f"      Primary cache size: {len(_cache)}")
        print(f"      Secondary index size: {len(_by_tool_call)}")
    
    print("\n3. Final cache state:\n")
    
    print("Primary cache contents:")
    for key, (sig, _) in _cache.items():
        print(f"  {key} -> {sig}")
    
    print("\nSecondary index contents:")
    for tc_id, sig in _by_tool_call.items():
        # Check if this tc_id is actually referenced in primary cache
        referenced = any(key.endswith(f":{tc_id}") for key in _cache.keys())
        status = "OK" if referenced else "ORPHANED"
        print(f"  {tc_id} -> {sig} {status}")
    
    # Count orphaned entries
    orphaned = 0
    for tc_id in _by_tool_call:
        if not any(key.endswith(f":{tc_id}") for key in _cache.keys()):
            orphaned += 1
    
    print(f"\n4. Result:\n")
    
    if orphaned > 0:
        print(f"MEMORY LEAK DETECTED!")
        print(f"   {orphaned} orphaned entries found in secondary index")
        print(f"   These entries will never be cleaned up and will accumulate")
        print(f"   every time the same tool_call_id appears across sessions.")
        
        print(f"\n   Root cause: The cleanup logic assumes each signature appears")
        print(f"   only once, but when same tc_id is reused across sessions,")
        print(f"   the condition `v != oldest_sig` fails to clean it up properly.")
        return False
    else:
        print("No memory leak in this scenario")
        return True


if __name__ == "__main__":
    demonstrate_memory_leak()