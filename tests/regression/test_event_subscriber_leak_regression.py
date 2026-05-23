"""Regression test for event bus subscriber memory leak fix.

This test verifies that event bus subscribers are properly unsubscribed
during shutdown to prevent memory leaks from strong references.
"""

from unittest.mock import MagicMock

import pytest
from src.core.services.event_bus import EventBus
from tests.utils.fake_clock import FakeClockContext


class TestEventSubscriberLeakRegression:
    """Regression tests for event bus subscriber memory leak fix."""

    @pytest.fixture
    def event_bus(self):
        """Create event bus instance."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribers_unsubscribed_on_shutdown(
        self, event_bus: EventBus
    ) -> None:
        """Test that all subscribers are unsubscribed during shutdown."""
        # Create mock event handlers
        handlers = []
        for _i in range(5):
            handler = MagicMock()
            handlers.append(handler)
            event_bus.subscribe(str, handler)

        # Verify handlers are called before shutdown
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event_before_shutdown")
            # Give handlers time to execute (reduced from 0.1s for performance)
            clock.advance(0.001)

        # All handlers should have been called
        for handler in handlers:
            handler.assert_called_once()

        # Reset handlers
        for handler in handlers:
            handler.reset_mock()

        # Shutdown event bus
        await event_bus.shutdown()

        # After shutdown, subscribers should be unsubscribed
        # Publish should return early without calling handlers
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event_after_shutdown")
            # Give handlers time to be called if they were still subscribed (reduced from 0.1s for performance)
            clock.advance(0.001)

        # Handlers should not be called after shutdown
        for handler in handlers:
            handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_shutdown_does_not_leak_subscribers(
        self, event_bus: EventBus
    ) -> None:
        """Test that partial shutdown doesn't leak subscribers."""
        # Create subscribers
        handlers = []
        for _i in range(3):
            handler = MagicMock()
            handlers.append(handler)
            event_bus.subscribe(str, handler)

        # Simulate partial shutdown scenario
        # Subscribe one more handler after some are already subscribed
        additional_handler = MagicMock()
        event_bus.subscribe(str, additional_handler)

        # Shutdown should clean up all subscribers
        await event_bus.shutdown()

        # Verify no handlers are called
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event")
            clock.advance(0.001)  # Reduced from 0.1s for performance

        for handler in [*handlers, additional_handler]:
            handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribers_unsubscribed_before_shutdown(
        self, event_bus: EventBus
    ) -> None:
        """Test that manually unsubscribing works correctly."""
        # Create and subscribe handlers
        handler1 = MagicMock()
        handler2 = MagicMock()
        handler3 = MagicMock()

        event_bus.subscribe(str, handler1)
        event_bus.subscribe(str, handler2)
        event_bus.subscribe(str, handler3)

        # Unsubscribe one handler manually
        event_bus.unsubscribe(str, handler2)

        # Publish event - handler2 should not be called
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event")
            clock.advance(0.001)  # Reduced from 0.1s for performance

        handler1.assert_called_once()
        handler2.assert_not_called()
        handler3.assert_called_once()

        # Shutdown should clean up remaining subscribers
        await event_bus.shutdown()

        # Publish again - no handlers should be called
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event2")
            clock.advance(0.001)  # Reduced from 0.1s for performance

        # handler1 and handler3 should not be called again (only once from before shutdown)
        assert handler1.call_count == 1
        assert handler3.call_count == 1

    @pytest.mark.asyncio
    async def test_multiple_event_types_subscribers_cleaned_up(
        self, event_bus: EventBus
    ) -> None:
        """Test that subscribers for multiple event types are cleaned up."""

        # Create event classes
        class EventType1:
            pass

        class EventType2:
            pass

        class EventType3:
            pass

        # Subscribe handlers for different event types
        handlers = {}
        for event_type in [EventType1, EventType2, EventType3]:
            handler = MagicMock()
            handlers[event_type] = handler
            event_bus.subscribe(event_type, handler)

        # Shutdown should clean up all subscribers
        await event_bus.shutdown()

        # Publish events - handlers should not be called
        async with FakeClockContext() as clock:
            await event_bus.publish(EventType1())
            await event_bus.publish(EventType2())
            await event_bus.publish(EventType3())
            clock.advance(0.001)  # Reduced from 0.1s for performance

        # All handlers should not be called
        for handler in handlers.values():
            handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, event_bus: EventBus) -> None:
        """Test that shutdown can be called multiple times safely."""
        # Subscribe handlers
        handler = MagicMock()
        event_bus.subscribe(str, handler)

        # Call shutdown multiple times
        await event_bus.shutdown()
        await event_bus.shutdown()
        await event_bus.shutdown()

        # Should not raise exceptions and handlers should not be called
        async with FakeClockContext() as clock:
            await event_bus.publish("test_event")
            clock.advance(0.001)  # Reduced from 0.1s for performance

        handler.assert_not_called()
