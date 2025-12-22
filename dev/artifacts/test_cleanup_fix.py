#!/usr/bin/env python3
"""
Direct test of the fixed cleanup logic.
"""

import time
from collections import OrderedDict


def test_fixed_cleanup():
    """Test the fixed cleanup logic directly."""
    
    print("=== Testing Fixed Cleanup Logic ===\n")
    
    # Simulate fixed logic
    _cache = OrderedDict([
        ("session1:tool_a", ("sig1", time.time())),
        ("session2:tool_a", ("sig2", time.time())),
        ("session1:tool_b", ("sig3", time.time())),
    ])
    
    _by_tool_call = {
        "tool_a": "sig1",
        "tool_b": "sig3",
    }
    
    print("Before eviction:")
    print("Cache:", list(_cache.keys()))
    print("Index:", _by_tool_call)
    
    # Remove oldest
    oldest_key, oldest_value = _cache.popitem(last=False)
    print(f"\nRemoving: {oldest_key}")
    
    # Apply FIXED cleanup logic
    new_by_tool_call = {}
    for cache_key, (sig, _) in _cache.items():
        tc_id = cache_key.split(":", 1)[1] if ":" in cache_key else cache_key
        new_by_tool_call[tc_id] = sig
    
    _by_tool_call = new_by_tool_call
    
    print("\nAfter fixed cleanup:")
    print("Cache:", list(_cache.keys()))
    print("Index:", _by_tool_call)
    
    # Verify correctness
    expected = {
        "tool_a": "sig2",  # session2:tool_a remains
        "tool_b": "sig3",  # session1:tool_b remains
    }
    
    if _by_tool_call == expected:
        print("\n✓ Fixed logic works correctly!")
        return True
    else:
        print(f"\n✗ Expected {expected}, got {_by_tool_call}")
        return False


if __name__ == "__main__":
    test_fixed_cleanup()