"""
Reproduction script for thought_signature_manager memory leak.

The _by_tool_call dict can grow unbounded because:
1. It stores mappings from tc_id -> signature
2. The same tc_id can appear in different sessions (session_id:tc_id)
3. When entries expire from _cache, _by_tool_call is only rebuilt if LRU eviction triggers
4. If cache never exceeds max size, _by_tool_call accumulates stale entries
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


async def test_unbounded_growth():
    """Test that demonstrates unbounded growth of _by_tool_call."""
    manager = ThoughtSignatureManager(max_cache_size=100, ttl_seconds=60)

    print(f"Initial state: _cache={len(manager._cache)}, _by_tool_call={len(manager._by_tool_call)}")

    # Simulate storing signatures for different sessions with the same tool_call_id
    # In real scenarios, a tool_call_id can appear in different sessions
    for i in range(200):
        tool_calls = [{"id": "tool_1", "extra_content": {"google": {"thought_signature": f"sig_{i}"}}}]
        manager.store_signatures_from_tool_calls(tool_calls, f"session_{i}")

        if i % 50 == 0:
            print(f"After {i} stores: _cache={len(manager._cache)}, _by_tool_call={len(manager._by_tool_call)}")

    print(f"\nAfter 200 stores: _cache={len(manager._cache)}, _by_tool_call={len(manager._by_tool_call)}")
    print(f"Expected _cache <= 100, but got {len(manager._cache)}")
    print(f"Expected _by_tool_call <= 100 (same as cache), but got {len(manager._by_tool_call)}")

    # Verify the leak: _by_tool_call should not exceed max_cache_size
    if len(manager._by_tool_call) > manager._max_cache_size:
        print("\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_by_tool_call ({len(manager._by_tool_call)}) exceeds max_cache_size ({manager._max_cache_size})")
        return True

    return False


async def test_same_tc_id_multiple_sessions():
    """
    Test the specific scenario: same tool_call_id in different sessions.

    This is the real-world scenario that triggers the leak.
    The cache key is "session_id:tc_id", so each session gets a unique entry.
    But _by_tool_call maps tc_id -> sig, so later sessions overwrite earlier ones.
    The problem is that _by_tool_call grows with new tc_ids even if cache stays within limits.
    """
    manager = ThoughtSignatureManager(max_cache_size=100, ttl_seconds=60)

    print("\n" + "="*60)
    print("Test: Same tc_id in multiple sessions")
    print("="*60)

    # Store tool_1 in 100 different sessions
    for i in range(100):
        tool_calls = [{"id": f"tool_{i % 10}", "extra_content": {"google": {"thought_signature": f"sig_{i}"}}}]
        manager.store_signatures_from_tool_calls(tool_calls, f"session_{i}")

    print("Stored tool calls for 100 sessions (10 unique tool IDs)")
    print(f"_cache size: {len(manager._cache)} (should be <= 100)")
    print(f"_by_tool_call size: {len(manager._by_tool_call)} (should be <= 10)")

    # The cache should have 100 entries (one per session)
    # The _by_tool_call should have 10 entries (one per unique tc_id)
    # But in reality, _by_tool_call can grow due to stale entries

    if len(manager._by_tool_call) > 10:
        print("\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_by_tool_call ({len(manager._by_tool_call)}) has more entries than expected (10)")
        print("This indicates stale entries that weren't cleaned up")
        return True

    return False


async def test_scenario_with_expiration():
    """
    Test that expired entries don't cause _by_tool_call to leak.
    """
    manager = ThoughtSignatureManager(max_cache_size=100, ttl_seconds=1)

    print("\n" + "="*60)
    print("Test: Expired entries causing stale _by_tool_call entries")
    print("="*60)

    # Store many tool calls
    for i in range(200):
        tool_calls = [{"id": f"tool_{i}", "extra_content": {"google": {"thought_signature": f"sig_{i}"}}}]
        manager.store_signatures_from_tool_calls(tool_calls, f"session_{i}")

    print("After storing 200 tool calls:")
    print(f"  _cache: {len(manager._cache)}")
    print(f"  _by_tool_call: {len(manager._by_tool_call)}")

    # Wait for TTL to expire
    print("\nWaiting 2 seconds for TTL to expire...")
    await asyncio.sleep(2)

    # Clean expired entries
    manager._clean_expired_entries()

    print("\nAfter cleanup:")
    print(f"  _cache: {len(manager._cache)}")
    print(f"  _by_tool_call: {len(manager._by_tool_call)}")

    # After cleaning expired entries, _by_tool_call should also be small
    if len(manager._by_tool_call) > len(manager._cache):
        print("\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_by_tool_call ({len(manager._by_tool_call)}) is larger than _cache ({len(manager._cache)})")
        print("Stale entries remain in _by_tool_call after cache cleanup")
        return True

    return False


async def main():
    """Run all tests."""
    leak_detected = False

    leak_detected |= await test_unbounded_growth()
    leak_detected |= await test_same_tc_id_multiple_sessions()
    leak_detected |= await test_scenario_with_expiration()

    if leak_detected:
        print("\n" + "="*60)
        print("MEMORY LEAK CONFIRMED!")
        print("="*60)
        sys.exit(1)
    else:
        print("\nNo memory leak detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
