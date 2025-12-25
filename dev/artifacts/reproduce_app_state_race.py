"""
Reproduction script for race condition in ApplicationStateService.

This script simulates concurrent access to _local_state dictionary
which lacks lock protection.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from src.core.services.application_state_service import ApplicationStateService


async def test_concurrent_writes():
    """Test concurrent writes to _local_state."""
    service = ApplicationStateService()
    errors = []

    async def set_command_prefix(iter_id: int):
        try:
            # Concurrent writes without locks
            for i in range(100):
                service._local_state[f"prefix_{iter_id}_{i}"] = f"value_{i}"
        except Exception as e:
            errors.append(f"Task {iter_id}: {e}")

    async def concurrent_reads(iter_id: int):
        try:
            # Concurrent reads during writes
            for i in range(100):
                _ = service._local_state.get(f"prefix_{iter_id}_{i}")
        except Exception as e:
            errors.append(f"Read task {iter_id}: {e}")

    # Launch 10 concurrent tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(set_command_prefix(i)))
        tasks.append(asyncio.create_task(concurrent_reads(i)))

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
    service = ApplicationStateService()
    errors = []

    async def modify_state(iter_id: int):
        try:
            for i in range(50):
                service.set_command_prefix(f"prefix_{iter_id}_{i}")
                service.set_api_key_redaction_enabled(i % 2 == 0)
                service.set_disable_commands(i % 2 == 0)
        except Exception as e:
            errors.append(f"Modify task {iter_id}: {e}")

    async def read_state(iter_id: int):
        try:
            for i in range(50):
                service.get_command_prefix()
                service.get_api_key_redaction_enabled()
                service.get_disable_commands()
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
    print("Testing ApplicationStateService for race conditions")
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
