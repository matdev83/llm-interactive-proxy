#!/usr/bin/env python3
"""
Reproduction script for memory leak in ThoughtSignatureManager.

This script demonstrates that the _by_tool_call secondary index can
accumulate stale entries due to flawed cleanup logic.
"""

import sys
import time
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def test_memory_leak():
    """Test for memory leak in ThoughtSignatureManager."""
    
    manager = ThoughtSignatureManager(max_cache_size=5, ttl_seconds=10)
    
    print("Testing ThoughtSignatureManager memory leak...")
    
    # Test the specific cleanup logic that's flawed
    print("\nStep 1: Fill cache with unique entries")
    for i in range(10):
        tc_id = f"tool_call_{i}"
        sig = f"signature_{i}"
        
        # Simulate storing with multiple sessions
        for session_id in ["session1", "session2"]:
            cache_key = f"{session_id}:{tc_id}"
            current_time = time.time()
            
            # Store in primary cache
            manager._cache[cache_key] = (sig, current_time)
            manager._by_tool_call[tc_id] = sig  # Secondary index - same tc_id, diff sessions
            
            # Simulate cache size enforcement (this happens in real code)
            if len(manager._cache) > manager._max_cache_size:
                oldest_key, oldest_value = manager._cache.popitem(last=False)
                oldest_sig, _ = oldest_value
                
                # This is the FLAWED cleanup logic
                manager._by_tool_call = {
                    k: v
                    for k, v in manager._by_tool_call.items()
                    if v != oldest_sig or any(k2.endswith(f":{k}") for k2 in manager._cache)
                }
        
        print(f"  After adding {tc_id}: primary={len(manager._cache)}, secondary={len(manager._by_tool_call)}")
    
    print(f"\nFinal state:")
    print(f"  Primary cache size: {len(manager._cache)}")
    print(f"  Secondary index size: {len(manager._by_tool_call)}")
    
    # The problem: When same tc_id is used across different sessions,
    # the cleanup logic fails to remove it properly
    
    print(f"\nSecondary index contents:")
    for tc_id, sig in manager._by_tool_call.items():
        # Check if this tc_id is actually referenced in primary cache
        referenced = any(key.endswith(f":{tc_id}") for key in manager._cache.keys())
        print(f"  {tc_id}: {sig[:12]}... (referenced: {referenced})")
    
    # Count orphaned entries
    orphaned = 0
    for tc_id in manager._by_tool_call:
        if not any(key.endswith(f":{tc_id}") for key in manager._cache.keys()):
            orphaned += 1
    
    if orphaned > 0:
        print(f"\n*** MEMORY LEAK DETECTED! ***")
        print(f"Found {orphaned} orphaned entries in secondary index")
        print(f"These entries will never be cleaned up!")
        return False
    else:
        print(f"\nNo memory leak detected in this test")
        return True


if __name__ == "__main__":
    try:
        result = test_memory_leak()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"Error running test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)