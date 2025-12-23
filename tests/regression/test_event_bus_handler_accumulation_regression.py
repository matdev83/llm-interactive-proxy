"""Regression test for EventBus handler accumulation memory leak fix.

This test verifies that EventBus enforces handler limits to prevent
unbounded memory growth when handlers are subscribed but never unsubscribed.
"""

from src.core.services.event_bus import EventBus


class TestEvent:
    """Test event class."""


class TestEventBusHandlerAccumulationRegression:
    """Regression tests for EventBus handler accumulation memory leak fix."""

    def test_handler_limit_enforced(self) -> None:
        """Test that handler limit is enforced when subscribing many handlers."""
        max_handlers = 1000
        bus = EventBus(max_total_handlers=max_handlers)

        # Attempt to subscribe more handlers than the limit
        num_handlers = 1500  # More than max to test limit
        subscribed_count = 0

        for _i in range(num_handlers):

            async def handler(event: TestEvent) -> None:
                pass

            # Count handlers before subscription
            handlers_before = bus._count_total_handlers()

            bus.subscribe(TestEvent, handler)

            # Count handlers after subscription
            handlers_after = bus._count_total_handlers()

            # If handler was added, increment count
            if handlers_after > handlers_before:
                subscribed_count += 1

            # Verify we never exceed the limit
            assert handlers_after <= max_handlers, (
                f"Handler count ({handlers_after}) exceeded max limit ({max_handlers}). "
                "Handler limit is not being enforced."
            )

        # Verify that not all handlers were subscribed (limit was enforced)
        total_handlers = bus._count_total_handlers()
        assert total_handlers <= max_handlers, (
            f"Final handler count ({total_handlers}) exceeded max limit ({max_handlers}). "
            "Handler accumulation leak is not fixed."
        )

        # Verify that some handlers were blocked
        assert subscribed_count <= max_handlers, (
            f"Too many handlers ({subscribed_count}) were subscribed. "
            f"Expected at most {max_handlers}."
        )

    def test_handler_limit_with_multiple_event_types(self) -> None:
        """Test that handler limit applies across all event types."""
        max_handlers = 500
        bus = EventBus(max_total_handlers=max_handlers)

        class EventType1:
            pass

        class EventType2:
            pass

        # Subscribe handlers for different event types
        for _i in range(300):

            async def handler1(event: EventType1) -> None:
                pass

            async def handler2(event: EventType2) -> None:
                pass

            bus.subscribe(EventType1, handler1)
            bus.subscribe(EventType2, handler2)

            # Verify total never exceeds limit
            total = bus._count_total_handlers()
            assert total <= max_handlers, (
                f"Total handler count ({total}) exceeded max limit ({max_handlers}) "
                "across multiple event types."
            )

        # Final verification
        final_total = bus._count_total_handlers()
        assert (
            final_total <= max_handlers
        ), f"Final total handler count ({final_total}) exceeded max limit ({max_handlers})."

    def test_handler_limit_with_topics(self) -> None:
        """Test that handler limit applies across all topics."""
        max_handlers = 300
        bus = EventBus(max_total_handlers=max_handlers)

        # Subscribe handlers with different topics
        topics = ["topic1", "topic2", "topic3"]
        for _i in range(200):
            for topic in topics:

                async def handler(event: TestEvent) -> None:
                    pass

                bus.subscribe(TestEvent, handler, topic=topic)

                # Verify total never exceeds limit
                total = bus._count_total_handlers()
                assert total <= max_handlers, (
                    f"Total handler count ({total}) exceeded max limit ({max_handlers}) "
                    f"across multiple topics."
                )

        # Final verification
        final_total = bus._count_total_handlers()
        assert (
            final_total <= max_handlers
        ), f"Final total handler count ({final_total}) exceeded max limit ({max_handlers})."

    def test_count_total_handlers_accuracy(self) -> None:
        """Test that _count_total_handlers returns accurate count."""
        bus = EventBus(max_total_handlers=100)

        # Subscribe some handlers
        for _i in range(10):

            async def handler(event: TestEvent) -> None:
                pass

            bus.subscribe(TestEvent, handler)

        # Manually count handlers
        manual_count = sum(
            len(handlers)
            for topic_map in bus._handlers.values()
            for handlers in topic_map.values()
        )

        # Compare with method
        method_count = bus._count_total_handlers()

        assert manual_count == method_count, (
            f"Manual count ({manual_count}) doesn't match method count ({method_count}). "
            "_count_total_handlers() may be inaccurate."
        )
