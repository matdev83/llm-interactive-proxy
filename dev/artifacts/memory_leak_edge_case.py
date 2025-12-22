#!/usr/bin/env python3
"""
Test to find the actual memory leak in ThoughtSignatureManager.
Looking at edge cases in cleanup logic.
"""

import time
from collections import OrderedDict


def test_cleanup_edge_case():
    """
    Test the specific cleanup logic to find when it fails.
    
    Looking at the problematic cleanup:
    ```python
    self._by_tool_call = {
        k: v
        for k, v in self._by_tool_call.items()
        if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in self._cache)
    }
    ```
    
    The bug is: `any(k2.endswith(f":{k}")` only checks if ANY cache key ends with `:{k}`,
    but doesn't check if the signature matches!
    """
    
    print("=== Testing Cleanup Logic Edge Case ===\n")
    
    # Setup scenario where bug manifests
    _cache = OrderedDict([
        ("session1:tool_a", ("sig1", time.time())),
        ("session2:tool_a", ("sig2", time.time())),  # Same tc_id, different sig
    ])
    
    _by_tool_call = {
        "tool_a": "sig1"  # Stale sig1
    }
    
    print("Initial state:")
    print("Primary cache:")
    for key, (sig, _) in _cache.items():
        print(f"  {key} -> {sig}")
    print(f"Secondary index: {_by_tool_call}")
    
    # Now remove session1:tool_a (oldest)
    print(f"\nRemoving oldest entry: session1:tool_a with sig1")
    oldest_key, oldest_value = _cache.popitem(last=False)
    oldest_sig, _ = oldest_value
    
    # Apply buggy cleanup logic
    _by_tool_call = {
        k: v
        for k, v in _by_tool_call.items()
        if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in _cache)
    }
    
    print(f"\nAfter cleanup:")
    print("Primary cache:")
    for key, (sig, _) in _cache.items():
        print(f"  {key} -> {sig}")
    print(f"Secondary index: {_by_tool_call}")
    
    # Check if bug exists
    tc_id = "tool_a"
    expected_sig = "sig2"  # Should be sig2 since only session2:tool_a remains
    actual_sig = _by_tool_call.get(tc_id)
    
    print(f"\nExpected {tc_id} -> {expected_sig}")
    print(f"Actual {tc_id} -> {actual_sig}")
    
    if actual_sig != expected_sig:
        print(f"\nBUG DETECTED!")
        print(f"Secondary index still points to sig1 which was removed!")
        print(f"This happens because:")
        print(f"  1. oldest_sig = 'sig1'")
        print(f"  2. v != oldest_sig is False (v = 'sig1')")
        print(f"  3. any(k2.endswith(f':tool_a')) is True (session2:tool_a exists)")
        print(f"  4. False or True = True, so entry kept")
        print(f"  5. But v is still the OLD signature!")
        return True
    
    return False


def test_with_different_values():
    """Test with actual values that might expose the bug."""
    
    print("\n=== Testing with Different Signatures ===\n")
    
    # More complex scenario
    _cache = OrderedDict([
        ("session1:tool_a", ("signature_abc", time.time())),
        ("session2:tool_a", ("signature_xyz", time.time())),  # Different signature
        ("session1:tool_b", ("signature_def", time.time())),
    ])
    
    _by_tool_call = {
        "tool_a": "signature_abc",  # Points to first signature
        "tool_b": "signature_def",
    }
    
    print("Before cleanup:")
    print("Cache keys:", list(_cache.keys()))
    print("By tool call:", _by_tool_call)
    
    # Remove oldest (session1:tool_a)
    oldest_key, oldest_value = _cache.popitem(last=False)
    oldest_sig, _ = oldest_value
    
    print(f"\nRemoved {oldest_key} with signature {oldest_sig}")
    
    # Apply cleanup
    _by_tool_call = {
        k: v
        for k, v in _by_tool_call.items()
        if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in _cache)
    }
    
    print("\nAfter cleanup:")
    print("Cache keys:", list(_cache.keys()))
    print("By tool call:", _by_tool_call)
    
    # Now check - tool_a should point to signature_xyz since session2:tool_a still exists
    # But _by_tool_call still has signature_abc!
    
    for tc_id in ["tool_a"]:
        # Find the correct signature from remaining cache
        correct_sig = None
        for key, (sig, _) in _cache.items():
            if key.endswith(f":{tc_id}"):
                correct_sig = sig
                break
        
        stored_sig = _by_tool_call.get(tc_id)
        
        print(f"\ntool_a analysis:")
        print(f"  Correct signature (from cache): {correct_sig}")
        print(f"  Stored signature (from index): {stored_sig}")
        
        if stored_sig != correct_sig:
            print(f"  MISMATCH! This is the memory leak bug!")
            print(f"  The secondary index points to stale signature {stored_sig}")
            print(f"  But cache only contains {correct_sig}")
            return True
        else:
            print(f"  Signatures match correctly")
    
    return False


if __name__ == "__main__":
    bug1 = test_cleanup_edge_case()
    bug2 = test_with_different_values()
    
    if bug1 or bug2:
        print(f"\n*** MEMORY LEAK CONFIRMED ***")
        print("The secondary index accumulates stale signature references!")
    else:
        print(f"\nNo memory leak detected in these scenarios")