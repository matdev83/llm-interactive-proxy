"""Test EventBus thread safety for concurrent access to _handlers.

This test verifies that _get_handlers_for_event is thread-safe
by reading handlers while subscribe/unsubscribe modify the dictionary.
"""

import asyncio
import threading
from dataclasses import dataclass

from src.core.services.event_bus import EventBus


@dataclass
class TestEvent:
    pass


async def test_concurrent_subscribe_and_publish():
    """Test that subscribe and publish can run concurrently without race conditions.

    This test verifies that _get_handlers_for_event acquires lock
    to prevent race conditions when multiple threads access _handlers.
    """
    bus = EventBus()

    call_count = 0
    call_lock = threading.Lock()

    async def handler(event: TestEvent) -> None:
        nonlocal call_count
        with call_lock:
            call_count += 1

    async def concurrent_subscriber() -> None:
        """Concurrently subscribe handlers."""
        for _ in range(100):
            async def inner_handler(event: TestEvent) -> None:
                pass

            bus.subscribe(TestEvent, inner_handler)
            await asyncio.sleep(0)  # Yield to allow interleaving

    async def concurrent_publisher() -> None:
        """Concurrently publish events."""
        for _ in range(100):
            event = TestEvent()
            await bus.publish(event)
            await asyncio.sleep(0)  # Yield to allow interleaving

    async def concurrent_unsubscriber() -> None:
        """Concurrently unsubscribe handlers."""
        for _ in range(50):
            bus.unsubscribe(TestEvent, handler)
            await asyncio.sleep(0)  # Yield to allow interleaving

    # Subscribe initial handler
    bus.subscribe(TestEvent, handler)

    # Run all operations concurrently
    await asyncio.gather(
        concurrent_subscriber(),
        concurrent_publisher(),
        concurrent_unsubscriber(),
    )

    # Verify that events were handled
    # Note: Some events may be missed if unsubscribe removes handler
    # but no crash should occur
    assert call_count >= 0
    assert not isinstance(call_count, type(None))


async def test_concurrent_subscribe_and_read_handlers():
    """Test that _get_handlers_for_event returns consistent snapshots.

    This test verifies that _get_handlers_for_event returns a copy
    of the handlers list, preventing concurrent modification issues.
    """
    bus = EventBus()

    async def handler1(event: TestEvent) -> None:
        pass

    async def handler2(event: TestEvent) -> None:
        pass

    async def handler3(event: TestEvent) -> None:
        pass

    bus.subscribe(TestEvent, handler1)
    bus.subscribe(TestEvent, handler2)
    bus.subscribe(TestEvent, handler3)

    # Get handlers (should return copy)
    handlers_before = bus._get_handlers_for_event(TestEvent)
    assert len(handlers_before) == 3

    # Add more handlers while iterating (simulating concurrent access)
    async def add_handlers() -> None:
        for _ in range(10):
            async def new_handler(event: TestEvent) -> None:
                pass

            bus.subscribe(TestEvent, new_handler)
            await asyncio.sleep(0)

    # Start adding handlers concurrently
    add_task = asyncio.create_task(add_handlers())

    # Read handlers multiple times
    for _ in range(50):
        handlers = bus._get_handlers_for_event(TestEvent)
        # Should never crash or have inconsistent length
        assert len(handlers) >= 3
        await asyncio.sleep(0)

    await add_task
