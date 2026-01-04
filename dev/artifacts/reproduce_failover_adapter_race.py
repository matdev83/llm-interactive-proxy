"""
Reproduction script for race condition in failover_command_handler.

This script simulates concurrent access to SessionStateApplicationStateAdapter's
_local_state dictionary which lacks lock protection.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from src.core.commands.handlers.failover_command_handler import (
    SessionStateApplicationStateAdapter,
)
from src.core.domain.session import Session


async def test_concurrent_writes():
    """Test concurrent writes to _local_state."""
    session = Session(
        session_id="test-session",
        state=None,
    )
    adapter = SessionStateApplicationStateAdapter(session)
    errors = []

    async def modify_state(iter_id: int):
        try:
            for i in range(100):
                adapter._local_state[f"key_{iter_id}_{i}"] = f"value_{i}"
        except Exception as e:
            errors.append(f"Write task {iter_id}: {e}")

    async def read_state(iter_id: int):
        try:
            for i in range(100):
                _ = adapter._local_state.get(f"key_{iter_id}_{i}")
        except Exception as e:
            errors.append(f"Read task {iter_id}: {e}")

    # Launch concurrent tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(modify_state(i)))
        tasks.append(asyncio.create_task(read_state(i)))

    await asyncio.gather(*tasks)

    if errors:
        print(f"RACE CONDITION DETECTED: {len(errors)} errors occurred")
        for err in errors[:5]:
            print(f"  - {err}")
        return True
    else:
        print("No errors detected (race condition may still exist)")
        return False


async def test_method_concurrency():
    """Test concurrent method calls that modify _local_state."""
    session = Session(
        session_id="test-session",
        state=None,
    )
    adapter = SessionStateApplicationStateAdapter(session)
    errors = []

    async def modify_state(iter_id: int):
        try:
            for i in range(50):
                adapter.set_command_prefix(f"prefix_{iter_id}_{i}")
                adapter.set_api_key_redaction_enabled(i % 2 == 0)
                adapter.set_disable_commands(i % 2 == 0)
                adapter.set_setting(f"key_{i}", f"value_{i}")
        except Exception as e:
            errors.append(f"Modify task {iter_id}: {e}")

    async def read_state(iter_id: int):
        try:
            for i in range(50):
                adapter.get_command_prefix()
                adapter.get_api_key_redaction_enabled()
                adapter.get_disable_commands()
                adapter.get_setting(f"key_{i}")
        except Exception as e:
            errors.append(f"Read task {iter_id}: {e}")

    # Launch concurrent tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(modify_state(i)))
        tasks.append(asyncio.create_task(read_state(i)))

    await asyncio.gather(*tasks)

    if errors:
        print(f"RACE CONDITION DETECTED in methods: {len(errors)} errors")
        for err in errors[:5]:
            print(f"  - {err}")
        return True
    else:
        print("No method errors detected")
        return False


async def main():
    print("=" * 60)
    print("Testing SessionStateApplicationStateAdapter for race conditions")
    print("=" * 60)

    print("\n1. Testing direct _local_state concurrent access...")
    result1 = await test_concurrent_writes()

    print("\n2. Testing method-level concurrent access...")
    result2 = await test_method_concurrency()

    if result1 or result2:
        print("\n" + "=" * 60)
        print("RACE CONDITIONS FOUND - FIX REQUIRED")
        print("=" * 60)
        sys.exit(1)
    else:
        print("\n" + "=" * 60)
        print("No explicit errors (race conditions may still exist)")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
