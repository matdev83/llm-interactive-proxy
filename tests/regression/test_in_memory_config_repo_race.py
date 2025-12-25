"""Regression test for InMemoryConfigRepository race condition."""

import asyncio

from src.core.repositories.in_memory_config_repository import InMemoryConfigRepository


async def test_concurrent_set_config_is_thread_safe():
    """Test that concurrent set_config operations are thread-safe."""
    repo = InMemoryConfigRepository()

    async def set_configs(suffix: int):
        for i in range(100):
            key = f"config-{suffix}-{i}"
            await repo.set_config(key, {"value": i, "suffix": suffix})

    # Create concurrent tasks
    tasks = [set_configs(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Should have approximately 1000 configs
    # With lock protection, should have exactly 1000
    assert (
        len(repo._configs) == 1000
    ), f"Expected 1000 configs, got {len(repo._configs)} - race condition!"


async def test_concurrent_set_and_delete_is_thread_safe():
    """Test that concurrent set and delete operations are thread-safe."""
    repo = InMemoryConfigRepository()

    async def set_and_delete(suffix: int):
        for i in range(50):
            key = f"config-{suffix}-{i}"
            await repo.set_config(key, {"value": i})
            await repo.delete_config(key)

    tasks = [set_and_delete(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # All deletes should have happened
    # Final state should be empty (all configs set then deleted)
    assert (
        len(repo._configs) == 0
    ), f"Expected 0 configs after all deletes, got {len(repo._configs)}"


async def test_concurrent_get_and_set_is_thread_safe():
    """Test that concurrent get and set operations are thread-safe."""
    repo = InMemoryConfigRepository()

    # Pre-populate
    await repo.set_config("config-0", {"initial": 0})

    async def get_and_set(suffix: int):
        for i in range(50):
            # Get existing config
            await repo.get_config("config-0")
            # Set new config
            key = f"config-{suffix}-{i}"
            await repo.set_config(key, {"value": i})

    tasks = [get_and_set(i) for i in range(5)]
    await asyncio.gather(*tasks)

    # Should have 1 (pre-existing) + 5 * 50 = 251 configs
    assert len(repo._configs) == 251, f"Expected 251 configs, got {len(repo._configs)}"


async def test_concurrent_delete_is_thread_safe():
    """Test that concurrent delete operations are thread-safe."""
    # Pre-populate
    repo = InMemoryConfigRepository()
    for i in range(100):
        await repo.set_config(f"config-{i}", {"value": i})

    async def delete_configs(suffix: int):
        for i in range(10):
            key = f"config-{(i * 10 + suffix) % 100}"
            await repo.delete_config(key)

    tasks = [delete_configs(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # Should have 100 - 100 = 0 configs remaining
    assert (
        len(repo._configs) == 0
    ), f"Expected 0 configs after deletes, got {len(repo._configs)}"


async def test_delete_nonexistent_does_not_error():
    """Test that deleting nonexistent key returns False."""
    repo = InMemoryConfigRepository()

    result = await repo.delete_config("nonexistent")
    assert result is False, "Should return False for nonexistent key"

    # Add and then delete
    await repo.set_config("test", {"value": 1})
    result = await repo.delete_config("test")
    assert result is True, "Should return True for existing key"


if __name__ == "__main__":
    asyncio.run(test_concurrent_set_config_is_thread_safe())
    asyncio.run(test_concurrent_set_and_delete_is_thread_safe())
    asyncio.run(test_concurrent_get_and_set_is_thread_safe())
    asyncio.run(test_concurrent_delete_is_thread_safe())
    asyncio.run(test_delete_nonexistent_does_not_error())
    print("All tests passed!")
