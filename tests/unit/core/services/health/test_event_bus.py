"""Tests for the EventBus class."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

import pytest
from src.core.domain.events import Event
from src.core.services.event_bus import EventBus

from tests.utils.fake_clock import FakeClockContext


@dataclass(frozen=True)
class TestEvent(Event):
    """Test event for testing."""

    event_type: ClassVar[str] = "test_event"
    message: str = ""


@dataclass(frozen=True)
class AnotherEvent(Event):
    """Another test event."""

    event_type: ClassVar[str] = "another_event"
    value: int = 0


class TestEventBus:
    """Tests for EventBus."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self) -> None:
        """Test basic subscribe and publish."""
        bus = EventBus()
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        bus.subscribe(TestEvent, handler)
        event = TestEvent(message="hello")
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].message == "hello"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self) -> None:
        """Test multiple handlers for same event type."""
        bus = EventBus()
        received1: list[TestEvent] = []
        received2: list[TestEvent] = []

        async def handler1(event: TestEvent) -> None:
            received1.append(event)

        async def handler2(event: TestEvent) -> None:
            received2.append(event)

        bus.subscribe(TestEvent, handler1)
        bus.subscribe(TestEvent, handler2)

        await bus.publish(TestEvent(message="test"))

        assert len(received1) == 1
        assert len(received2) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        """Test unsubscribing a handler."""
        bus = EventBus()
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        bus.subscribe(TestEvent, handler)
        await bus.publish(TestEvent(message="first"))
        assert len(received) == 1

        bus.unsubscribe(TestEvent, handler)
        await bus.publish(TestEvent(message="second"))
        assert len(received) == 1  # Handler not called again

    @pytest.mark.asyncio
    async def test_different_event_types(self) -> None:
        """Test that handlers only receive their event type."""
        bus = EventBus()
        test_received: list[TestEvent] = []
        another_received: list[AnotherEvent] = []

        async def test_handler(event: TestEvent) -> None:
            test_received.append(event)

        async def another_handler(event: AnotherEvent) -> None:
            another_received.append(event)

        bus.subscribe(TestEvent, test_handler)
        bus.subscribe(AnotherEvent, another_handler)

        await bus.publish(TestEvent(message="test"))
        await bus.publish(AnotherEvent(value=42))

        assert len(test_received) == 1
        assert len(another_received) == 1
        assert test_received[0].message == "test"
        assert another_received[0].value == 42

    @pytest.mark.asyncio
    async def test_handler_error_does_not_affect_others(self) -> None:
        """Test that errors in one handler don't affect others."""
        bus = EventBus()
        received: list[TestEvent] = []

        async def bad_handler(event: TestEvent) -> None:
            raise ValueError("Intentional error")

        async def good_handler(event: TestEvent) -> None:
            received.append(event)

        bus.subscribe(TestEvent, bad_handler)
        bus.subscribe(TestEvent, good_handler)

        # Should not raise, and good_handler should still be called
        await bus.publish(TestEvent(message="test"))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_nowait(self) -> None:
        """Test publish_nowait doesn't block."""
        bus = EventBus()
        received: list[TestEvent] = []
        event_processed = asyncio.Event()

        async def slow_handler(event: TestEvent) -> None:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                clock.advance(0.1)
                await sleep_task
            received.append(event)
            event_processed.set()

        bus.subscribe(TestEvent, slow_handler)
        await bus.publish_nowait(TestEvent(message="test"))

        # Handler hasn't completed yet
        assert len(received) == 0

        # Wait for handler to complete
        await asyncio.wait_for(event_processed.wait(), timeout=1.0)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_has_subscribers(self) -> None:
        """Test has_subscribers method."""
        bus = EventBus()

        async def handler(event: TestEvent) -> None:
            pass

        assert bus.has_subscribers(TestEvent) is False

        bus.subscribe(TestEvent, handler)
        assert bus.has_subscribers(TestEvent) is True
        assert bus.has_subscribers(AnotherEvent) is False

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        """Test graceful shutdown."""
        bus = EventBus()
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        bus.subscribe(TestEvent, handler)
        await bus.shutdown()

        # After shutdown, publish should not call handlers
        await bus.publish(TestEvent(message="after shutdown"))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_no_duplicate_subscription(self) -> None:
        """Test that same handler is not subscribed twice."""
        bus = EventBus()
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        bus.subscribe(TestEvent, handler)
        bus.subscribe(TestEvent, handler)  # Subscribe again

        await bus.publish(TestEvent(message="test"))
        # Handler should only be called once
        assert len(received) == 1
