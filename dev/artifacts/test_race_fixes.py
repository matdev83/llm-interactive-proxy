"""Test that both race condition fixes work correctly."""

import asyncio

from src.core.di.container import ServiceCollection
from src.core.services.production_concurrency_guard import ConcurrencyGuard


class DummyService:
    def __init__(self):
        self.id = id(self)


async def test_di_container():
    """Test DI container is thread-safe."""
    print("Testing DI Container...")
    collection = ServiceCollection()
    collection.register_singleton(DummyService)
    provider = collection.build_service_provider()

    async def get_service(i):
        return provider.get_required_service(DummyService)

    tasks = [get_service(i) for i in range(50)]
    instances = await asyncio.gather(*tasks)

    first = instances[0]
    for inst in instances[1:]:
        assert inst is first, "Expected same singleton instance"

    print("DI Container OK: Only 1 singleton instance created")


async def test_concurrency_guard():
    """Test concurrency guard is thread-safe."""
    print("Testing ConcurrencyGuard...")
    guard = ConcurrencyGuard(max_concurrent=2, name="test")

    success_count = 0
    rejected_count = 0

    async def try_acquire(i):
        nonlocal success_count, rejected_count
        try:
            async with guard.acquire(f"op_{i}"):
                success_count += 1
                await asyncio.sleep(0.01)
        except Exception as e:
            if "limit reached" in str(e):
                rejected_count += 1

    tasks = [try_acquire(i) for i in range(10)]
    await asyncio.gather(*tasks)

    print(f"ConcurrencyGuard OK: success={success_count}, rejected={rejected_count}")
    assert success_count == 2, "Expected 2 successes with limit=2"
    assert rejected_count == 8, "Expected 8 rejects"


if __name__ == "__main__":
    print("=== Testing Race Condition Fixes ===")
    asyncio.run(test_di_container())
    asyncio.run(test_concurrency_guard())
    print("All tests passed!")
