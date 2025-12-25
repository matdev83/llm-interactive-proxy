"""Regression test for DI container thread safety.

This test verifies that that DI container's singleton and scoped
instance caching is thread-safe under concurrent access.
"""

import asyncio
import threading

import pytest_asyncio
from src.core.di.container import (
    ServiceCollection,
)


class CounterService:
    """Test service that tracks instance count."""

    instance_count = 0
    lock = threading.Lock()

    def __init__(self):
        self.instance_id = id(self)
        with CounterService.lock:
            CounterService.instance_count += 1


class ScopedCounterService:
    """Test service for scoped lifetime."""

    def __init__(self):
        self.instance_id = id(self)


class TestDIContainerThreadSafety:
    """Test suite for DI container thread safety."""

    @pytest_asyncio.fixture(autouse=True)
    def set_event_loop_policy(self):
        policy = asyncio.WindowsSelectorEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)

    async def test_singleton_concurrent_access_safety(self):
        """Test that singleton service returns same instance under concurrent access."""
        collection = ServiceCollection()
        collection.register_singleton(CounterService)

        provider = collection.build_service_provider()

        # Reset counter
        CounterService.instance_count = 0

        async def get_service(i):
            # Get service from different coroutines concurrently
            return provider.get_required_service(CounterService)

        # Launch 50 concurrent requests
        tasks = [get_service(i) for i in range(50)]
        instances = await asyncio.gather(*tasks)

        # All should return the same instance
        first_instance = instances[0]
        for instance in instances[1:]:
            assert (
                instance is first_instance
            ), f"Different singleton instances returned: {id(instance)} vs {id(first_instance)}"

        # Should have created exactly 1 instance total
        assert (
            CounterService.instance_count == 1
        ), f"Expected 1 instance created, but got {CounterService.instance_count}"

    async def test_scoped_per_scope_safety(self):
        """Test that scoped service returns same instance within same scope."""
        collection = ServiceCollection()
        collection.add_scoped(ScopedCounterService)

        provider = collection.build_service_provider()
        scope = provider.create_scope()

        async def get_service(i):
            # Get service from same scope concurrently
            return scope.service_provider.get_required_service(ScopedCounterService)

        # Launch 50 concurrent requests from same scope
        tasks = [get_service(i) for i in range(50)]
        instances = await asyncio.gather(*tasks)

        # All should return the same instance within a scope
        first_instance = instances[0]
        for instance in instances[1:]:
            assert (
                instance is first_instance
            ), f"Different scoped instances in same scope: {id(instance)} vs {id(first_instance)}"

    async def test_multiple_scopes_independence(self):
        """Test that different scopes get independent instances."""
        collection = ServiceCollection()
        collection.add_scoped(ScopedCounterService)

        provider = collection.build_service_provider()

        # Create two scopes
        scope1 = provider.create_scope()
        scope2 = provider.create_scope()

        # Get service from both scopes
        instance1 = scope1.service_provider.get_required_service(ScopedCounterService)
        instance2 = scope2.service_provider.get_required_service(ScopedCounterService)

        # Should be different instances
        assert (
            instance1 is not instance2
        ), "Different scopes should have independent instances"
        assert instance1.instance_id != instance2.instance_id

    async def test_mixed_lifetime_access(self):
        """Test concurrent access to mixed singleton/scoped services."""
        collection = ServiceCollection()
        collection.register_singleton(CounterService)
        collection.add_scoped(ScopedCounterService)

        provider = collection.build_service_provider()
        scope = provider.create_scope()

        # Reset counter
        CounterService.instance_count = 0

        async def get_services(i):
            # Mix singleton and scoped access
            _ = provider.get_required_service(CounterService)
            _ = scope.service_provider.get_required_service(ScopedCounterService)

        # Launch 100 concurrent mixed requests
        tasks = [get_services(i) for i in range(100)]
        await asyncio.gather(*tasks)

        # Singleton should still only have 1 instance
        assert (
            CounterService.instance_count == 1
        ), f"Expected 1 singleton instance, got {CounterService.instance_count}"
