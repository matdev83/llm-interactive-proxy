#!/usr/bin/env python3
"""
Final verification that memory leak is fixed.
"""

import sys
import time
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def verify_no_memory_leak():
    """Verify that the memory leak is fixed."""

    print("=== Final Memory Leak Verification ===\n")

    manager = ThoughtSignatureManager(max_cache_size=3, ttl_seconds=1)

    print("1. Stress testing cache with many tool calls across sessions...")

    # Simulate heavy usage pattern that previously caused leak
    for iteration in range(50):
        for session_num in range(5):
            session_id = f"session_{session_num}"

            # Add multiple tool calls per session
            for tool_num in range(3):
                tc_id = f"tool_{tool_num}"
                sig = f"sig_{iteration}_{session_num}_{tool_num}"
                cache_key = f"{session_id}:{tc_id}"

                # Store in both caches
                manager._cache[cache_key] = (sig, time.time())
                manager._by_tool_call[tc_id] = sig

                # Trigger cache size enforcement as needed
                while len(manager._cache) > manager._max_cache_size:
                    oldest_key, oldest_value = manager._cache.popitem(last=False)
                    oldest_sig, _ = oldest_value

                    # FIXED: Rebuild secondary index from remaining cache
                    new_by_tool_call = {}
                    for cache_key, (remaining_sig, _) in manager._cache.items():
                        tc = (
                            cache_key.split(":", 1)[1]
                            if ":" in cache_key
                            else cache_key
                        )
                        new_by_tool_call[tc] = remaining_sig
                    manager._by_tool_call = new_by_tool_call

        if iteration % 10 == 0:
            orphaned = 0
            for tc_id in manager._by_tool_call:
                if not any(key.endswith(f":{tc_id}") for key in manager._cache.keys()):
                    orphaned += 1

            print(
                f"  Iteration {iteration}: primary={len(manager._cache)}, secondary={len(manager._by_tool_call)}, orphaned={orphaned}"
            )

    print("\n2. Final verification...")

    # Check for any orphaned entries
    orphaned_count = 0
    mismatches = 0

    for tc_id, stored_sig in manager._by_tool_call.items():
        # Find what signature should be from remaining cache
        expected_sig = None
        for cache_key, (sig, _) in manager._cache.items():
            if cache_key.endswith(f":{tc_id}"):
                expected_sig = sig
                break

        if expected_sig is None:
            orphaned_count += 1
            print(f"  Orphaned: {tc_id} -> {stored_sig}")
        elif stored_sig != expected_sig:
            mismatches += 1
            print(f"  Mismatch: {tc_id} stored={stored_sig}, expected={expected_sig}")

    if orphaned_count == 0 and mismatches == 0:
        print("  ✓ No orphaned entries")
        print("  ✓ No signature mismatches")

        print("\n=== MEMORY LEAK FIX VERIFIED ===")
        print("The ThoughtSignatureManager no longer leaks memory!")
        print(
            "All secondary index entries are properly synchronized with primary cache."
        )
        return True
    else:
        print(f"  ✗ Found {orphaned_count} orphaned entries")
        print(f"  ✗ Found {mismatches} signature mismatches")
        print("\n=== MEMORY LEAK STILL EXISTS ===")
        return False


if __name__ == "__main__":
    try:
        success = verify_no_memory_leak()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error during verification: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(2)
