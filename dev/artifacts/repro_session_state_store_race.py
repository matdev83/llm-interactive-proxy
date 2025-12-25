"""Reproduction script for SessionStateStore race condition.

This script demonstrates the race condition in SessionStateStore where
_concurrent get/set operations can cause data loss or corruption.
"""
import asyncio

from src.services.steering.session_state_store import SessionStateStore


async def test_concurrent_get_set():
    """Test concurrent get/set operations on same session."""
    store = SessionStateStore(ttl_seconds=10, max_sessions=100)
    session_id = "test-session-123"

    async def set_value(key_suffix):
        """Concurrent setter task."""
        for i in range(100):
            await store.set(session_id, f"key_{key_suffix}_{i}", f"value_{i}")

    async def get_value():
        """Concurrent getter task."""
        for i in range(100):
            await store.get(session_id, f"key_0_{i}", default=None)

    # Launch concurrent operations
    async with asyncio.TaskGroup() as tg:
        tg.create_task(set_value(0))
        tg.create_task(set_value(1))
        tg.create_task(set_value(2))
        tg.create_task(get_value())

    # Verify data integrity
    success_count = 0
    for i in range(100):
        val = await store.get(session_id, f"key_0_{i}")
        if val == f"value_{i}":
            success_count += 1

    print(f"Data integrity check: {success_count}/100 values correct")
    return success_count == 100


async def test_concurrent_prune():
    """Test concurrent pruning and access operations."""
    store = SessionStateStore(ttl_seconds=0, max_sessions=10)

    # Create many sessions
    for i in range(50):
        await store.set(f"session-{i}", "key", f"value-{i}")

    # Concurrent prune + access
    async def prune_and_access(session_suffix):
        for i in range(10):
            sid = f"session-{session_suffix}-{i}"
            await store.get(sid, "key")
            await store.prune()

    async with asyncio.TaskGroup() as tg:
        for s in range(5):
            tg.create_task(prune_and_access(s))

    print("Concurrent prune test completed")
    return True


async def main():
    """Run all reproduction tests."""
    print("=" * 60)
    print("SessionStateStore Race Condition Reproduction")
    print("=" * 60)

    result1 = await test_concurrent_get_set()
    result2 = await test_concurrent_prune()

    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"  Concurrent get/set test: {'PASS' if result1 else 'FAIL (race condition detected)'}")
    print(f"  Concurrent prune test: {'PASS' if result2 else 'FAIL'}")
    print("=" * 60)

    if not result1:
        return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
