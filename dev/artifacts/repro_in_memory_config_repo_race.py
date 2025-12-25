"""Repro script for InMemoryConfigRepository race condition."""

import asyncio

from src.core.repositories.in_memory_config_repository import InMemoryConfigRepository


async def test_concurrent_set_and_delete():
    """Test that concurrent set_config and delete_config operations are thread-safe."""
    repo = InMemoryConfigRepository()

    async def set_and_delete(key_suffix: int):
        for i in range(100):
            key = f"config-{key_suffix}-{i}"
            # Set config
            await repo.set_config(key, {"value": i})
            # Then delete it
            await repo.delete_config(key)

    # Create many concurrent tasks
    tasks = [set_and_delete(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Check if repository is in consistent state
    print(f"Repository has {len(repo._configs)} configurations")
    print("Race condition may cause exceptions or inconsistent state")


async def test_concurrent_set_operations():
    """Test that concurrent set_config operations are thread-safe."""
    repo = InMemoryConfigRepository()

    async def set_configs(key_suffix: int):
        for i in range(100):
            key = f"config-{key_suffix}-{i}"
            await repo.set_config(key, {"value": i, "suffix": key_suffix})

    tasks = [set_configs(i) for i in range(10)]
    await asyncio.gather(*tasks)

    print(f"Repository has {len(repo._configs)} configurations (expected ~1000)")


async def main():
    print("=" * 60)
    print("Testing InMemoryConfigRepository race conditions...")
    print("=" * 60)

    print("\nTest 1: Concurrent set and delete operations")
    await test_concurrent_set_and_delete()

    print("\nTest 2: Concurrent set operations")
    await test_concurrent_set_operations()

    print("\n" + "=" * 60)
    print("Tests complete - check for exceptions")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
