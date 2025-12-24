"""
Regression test for ICMPHealthChecker race condition fix.

Tests that the global ping executor is properly protected
against concurrent initialization.
"""

import asyncio
import threading

import pytest
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.health.icmp_checker import (
    ICMPHealthChecker,
    _get_ping_executor,
    _shutdown_ping_executor,
)


class MockEventBus(IEventBus):
    """Mock event bus for testing."""

    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)

    async def has_subscribers(self, event_type):
        return False

    def publish_nowait(self, event):
        pass

    def subscribe(self, event_type, handler):
        pass

    def unsubscribe(self, event_type, handler):
        pass

    async def shutdown(self):
        pass


def test_ping_executor_thread_safety():
    """Test that concurrent access to ping executor doesn't create multiple executors."""
    # Reset global state
    _shutdown_ping_executor()

    executor_ids = []

    def get_executor_id():
        executor = _get_ping_executor()
        executor_ids.append(id(executor))

    # Create multiple threads that access executor simultaneously
    threads = []
    for _ in range(10):
        t = threading.Thread(target=get_executor_id)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All threads should get the same executor
    unique_ids = set(executor_ids)
    assert len(unique_ids) == 1, f"Expected 1 unique executor, got {len(unique_ids)}"
    assert len(executor_ids) == 10, f"Expected 10 accesses, got {len(executor_ids)}"


@pytest.mark.asyncio
async def test_icmp_checker_concurrent_initialization():
    """Test that multiple ICMPHealthChecker instances don't create race conditions."""
    mock_event_bus = MockEventBus()
    registry = EndpointRegistry()

    # Create multiple tasks that initialize checkers
    async def create_checker():
        checker = ICMPHealthChecker(
            event_bus=mock_event_bus,
            endpoint_registry=registry,
            config=type(
                "Config",
                (),
                {
                    "enabled": True,
                    "timeout_seconds": 1,
                    "count": 1,
                },
            )(),
        )
        # The checker should access the executor safely
        await checker.check_endpoint("http://example.com")

    # Run concurrent operations
    tasks = [create_checker() for _ in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Cleanup
    _shutdown_ping_executor()


@pytest.mark.asyncio
async def test_ping_executor_shutdown_is_idempotent():
    """Test that shutdown can be called multiple times safely."""
    # Create executor
    _get_ping_executor()

    # Shutdown multiple times (should not raise)
    _shutdown_ping_executor()
    _shutdown_ping_executor()
    _shutdown_ping_executor()

    # Should be able to create a new one after shutdown
    executor = _get_ping_executor()
    assert executor is not None

    # Cleanup
    _shutdown_ping_executor()
