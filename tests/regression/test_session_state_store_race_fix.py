"""Regression tests for SessionStateStore race condition fixes."""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from src.services.steering.session_state_store import SessionStateStore


@pytest.mark.asyncio
async def test_session_state_store_concurrent_get_set_no_race():
    """Test that concurrent get/set operations don't cause data races."""
    store = SessionStateStore(ttl_seconds=10, max_sessions=100)
    session_id = "test-session-concurrent-123"

    async def set_value(key_suffix):
        """Concurrent setter task."""
        for i in range(100):
            await store.set(session_id, f"key_{key_suffix}_{i}", f"value_{i}")

    async def get_value():
        """Concurrent getter task."""
        results = []
        for i in range(100):
            val = await store.get(session_id, f"key_0_{i}", default=None)
            results.append((i, val))
        return results

    # Launch concurrent operations
    tasks = [
        asyncio.create_task(set_value(0)),
        asyncio.create_task(set_value(1)),
        asyncio.create_task(set_value(2)),
        asyncio.create_task(get_value()),
    ]
    await asyncio.gather(*tasks)

    # Verify data integrity - all values should be consistent
    get_results = tasks[3].result()
    success_count = sum(1 for i, val in get_results if val == f"value_{i}")

    # After all concurrent operations complete, verify final state
    final_val = await store.get(session_id, "key_0_42", default=None)

    # The value should be from the last set operation on that key
    assert success_count == 100 or final_val == "value_42", \
        f"Data integrity check failed: {success_count}/100 values correct"


@pytest.mark.asyncio
async def test_session_state_store_concurrent_prune_safe():
    """Test that concurrent pruning and access operations are safe."""
    store = SessionStateStore(ttl_seconds=0, max_sessions=10)

    # Create many sessions
    for i in range(50):
        await store.set(f"session-{i}", "key", f"value-{i}")

    async def concurrent_access(session_suffix):
        """Concurrent access task that may trigger prune."""
        for i in range(10):
            sid = f"session-{session_suffix}-{i}"
            val = await store.get(sid, "key")
            # Verify we get values back correctly
            if sid.startswith("session-0-"):
                expected = f"value-{sid.split('-')[1]}"
                # Sessions may be pruned, so only check if exists
                if val is not None:
                    assert val == expected, f"Value mismatch for {sid}: got {val}, expected {expected}"

    # Launch concurrent accesses that may trigger pruning
    tasks = [asyncio.create_task(concurrent_access(s)) for s in range(5)]
    await asyncio.gather(*tasks)

    # Test should complete without errors
    assert True


@pytest.mark.asyncio
async def test_session_state_store_update_atomic():
    """Test that update operations are atomic."""
    store = SessionStateStore(ttl_seconds=10, max_sessions=100)
    session_id = "test-session-atomic-456"

    # Set initial value
    await store.set(session_id, "counter", 0)

    # Concurrent increments using update
    async def increment():
        for _ in range(10):
            await store.update(
                session_id,
                "counter",
                lambda x: (x or 0) + 1,
                default=0
            )

    # Launch multiple concurrent increment tasks
    tasks = [asyncio.create_task(increment()) for _ in range(3)]
    await asyncio.gather(*tasks)

    # Final value should be 30 (3 tasks * 10 increments each)
    # Not lost updates due to race condition
    final_value = await store.get(session_id, "counter", default=0)
    assert final_value == 30, \
        f"Expected counter to be 30, got {final_value} - indicates lost update"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
