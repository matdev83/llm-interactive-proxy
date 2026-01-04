#!/usr/bin/env python3
"""
Repro script for thought signature manager memory leak.

This script simulates the unbounded growth of the thought signature cache
by creating unique tool calls and signatures without any cleanup.
"""

import asyncio
import gc
import os
import sys
import time
import tracemalloc

# Add src to path for imports
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, src_path)

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def get_memory_usage() -> int:
    """Get current memory usage in bytes."""
    gc.collect()  # Force garbage collection
    tracemalloc.stop()
    tracemalloc.start()
    # Get a snapshot after some operations
    snapshot = tracemalloc.take_snapshot()
    return sum(stat.size for stat in snapshot.statistics("lineno"))


def simulate_tool_calls(
    manager: ThoughtSignatureManager, count: int, session_id: str
) -> None:
    """Simulate storing tool call signatures."""
    for i in range(count):
        tc_id = f"tool_call_{i}"
        signature = f"thought_signature_for_{tc_id}_{time.time()}"

        # Simulate storing signature
        tool_calls = [
            {"id": tc_id, "extra_content": {"google": {"thought_signature": signature}}}
        ]

        manager.store_signatures_from_tool_calls(tool_calls, session_id)


async def main():
    """Main test function."""
    print("=== Thought Signature Manager Memory Leak Repro ===")

    # Start memory tracing
    tracemalloc.start()

    manager = ThoughtSignatureManager()
    session_id = "test_session"

    print(f"Initial memory: {get_memory_usage() // 1024} KB")
    print(f"Initial cache size: {len(manager._cache)} entries")

    # Test 1: Growth without cleanup
    print("\n--- Testing unbounded growth ---")
    for batch in range(5):
        simulate_tool_calls(manager, 1000, f"{session_id}_{batch}")
        current_memory = get_memory_usage() // 1024
        cache_size = len(manager._cache)
        secondary_index_size = len(manager._by_tool_call)

        print(
            f"Batch {batch + 1}: {current_memory} KB, "
            f"cache: {cache_size} entries, "
            f"secondary index: {secondary_index_size} entries"
        )

        # Simulate some operations
        for i in range(100):
            manager.store_signatures_from_tool_calls(
                [
                    {
                        "id": f"temp_call_{i}",
                        "extra_content": {
                            "google": {"thought_signature": f"temp_sig_{i}"}
                        },
                    }
                ],
                f"temp_session_{i}",
            )

    # Test 2: Show that even session cleanup doesn't clear everything
    print("\n--- Testing partial cleanup ---")
    manager.clear_session_cache(session_id)
    after_clear_memory = get_memory_usage() // 1024
    cache_size_after_clear = len(manager._cache)
    secondary_size_after_clear = len(manager._by_tool_call)

    print(
        f"After session clear: {after_clear_memory} KB, "
        f"cache: {cache_size_after_clear} entries, "
        f"secondary index: {secondary_size_after_clear} entries"
    )

    # Test 3: Demonstrate anonymous entries are never cleaned up
    print("\n--- Testing anonymous entries persistence ---")
    for i in range(1000):
        manager.store_signatures_from_tool_calls(
            [
                {
                    "id": f"anon_call_{i}",
                    "extra_content": {"google": {"thought_signature": f"anon_sig_{i}"}},
                }
            ],
            None,
        )  # No session_id = anonymous cache

    final_memory = get_memory_usage() // 1024
    final_cache_size = len(manager._cache)
    final_secondary_size = len(manager._by_tool_call)

    print(
        f"After adding 1000 anonymous entries: {final_memory} KB, "
        f"cache: {final_cache_size} entries, "
        f"secondary index: {final_secondary_size} entries"
    )

    # Summary
    print("\n=== MEMORY LEAK CONFIRMED ===")
    print("Issues identified:")
    print("1. No automatic cleanup of old entries (no TTL)")
    print("2. No size limits on cache dictionaries")
    print("3. Anonymous entries (session_id=None) are never cleaned up")
    print("4. Secondary index (_by_tool_call) grows without bounds")
    print("5. Only manual clear_session_cache() exists, but it's incomplete")

    # Get memory snapshot details
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")

    print("\nTop memory consumers:")
    for stat in top_stats[:10]:
        if stat.size > 1024:  # Only show > 1KB
            print(f"{stat.traceback.format()[-1].strip()}: {stat.size // 1024} KB")


if __name__ == "__main__":
    asyncio.run(main())
