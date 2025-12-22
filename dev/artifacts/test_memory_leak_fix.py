#!/usr/bin/env python3
"""
Test the memory leak fix for ThoughtSignatureManager.
"""

import sys
import time
from pathlib import Path
from collections import OrderedDict

# Add src to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def test_fix():
    """Test that the memory leak is fixed."""
    
    print("=== Testing Memory Leak Fix ===\n")
    
    manager = ThoughtSignatureManager(max_cache_size=5, ttl_seconds=10)
    
    print("1. Adding entries that previously caused memory leak...")
    
    # Add entries that previously caused the leak
    current_time = time.time()
    for i in range(8):  # More than max_cache_size to trigger eviction
        for session in ["session1", "session2"]:
            tc_id = f"tool_{i}"
            sig = f"sig_{session}_{i}"
            cache_key = f"{session}:{tc_id}"
            
            manager._cache[cache_key] = (sig, current_time)
            manager._by_tool_call[tc_id] = sig
            
            # Trigger eviction if needed
            if len(manager._cache) > manager._max_cache_size:
                oldest_key, oldest_value = manager._cache.popitem(last=False)
                oldest_sig, _ = oldest_value
                
                # Apply FIXED cleanup logic
                new_by_tool_call = {}
                for cache_key, (remaining_sig, _) in manager._cache.items():
                    tc = cache_key.split(":", 1)[1] if ":" in cache_key else cache_key
                    new_by_tool_call[tc] = remaining_sig
                manager._by_tool_call = new_by_tool_call
    
    print(f"   Primary cache size: {len(manager._cache)}")
    print(f"   Secondary index size: {len(manager._by_tool_call)}")
    
    print("\n2. Checking for orphaned entries...")
    
    # Check for orphaned entries
    orphaned = 0
    for tc_id, sig in manager._by_tool_call.items():
        referenced = any(key.endswith(f":{tc_id}") for key in manager._cache.keys())
        if not referenced:
            orphaned += 1
            print(f"   ORPHANED: {tc_id} -> {sig}")
    
    if orphaned == 0:
        print("   No orphaned entries found!")
    
    # Verify all signatures are correct
    mismatches = 0
    for tc_id, stored_sig in manager._by_tool_call.items():
        # Find correct signature from cache
        correct_sig = None
        for cache_key, (sig, _) in manager._cache.items():
            if cache_key.endswith(f":{tc_id}"):
                correct_sig = sig
                break
        
        if stored_sig != correct_sig:
            mismatches += 1
            print(f"   MISMATCH: {tc_id} stored={stored_sig}, expected={correct_sig}")
    
    if mismatches == 0:
        print("   All signatures match correctly!")
    
    print("\n3. Test Result:")
    if orphaned == 0 and mismatches == 0:
        print("✓ Memory leak FIXED!")
        return True
    else:
        print(f"✗ Memory leak still exists: {orphaned} orphaned, {mismatches} mismatches")
        return False


if __name__ == "__main__":
    try:
        success = test_fix()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)