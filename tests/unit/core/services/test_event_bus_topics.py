"""Tests for topic-based event bus subscriptions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from src.core.services.event_bus import EventBus


@dataclass
class TestEvent:
    """Simple test event."""

    message: str


@dataclass
class ChildEvent(TestEvent):
    """Child event for inheritance testing."""

    extra: str = ""


class TestEventBusTopics:
    """Tests for topic-based subscription support in EventBus."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create a fresh event bus for each test."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_with_topic_receives_topic_events(
        self, event_bus: EventBus
    ) -> None:
        """Test that a topic subscriber receives events for that topic."""
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        event_bus.subscribe(TestEvent, handler, topic="topic1")

        await event_bus.publish(TestEvent(message="hello"), topic="topic1")
        await event_bus.publish(TestEvent(message="world"), topic="topic1")

        assert len(received) == 2
        assert received[0].message == "hello"
        assert received[1].message == "world"

    @pytest.mark.asyncio
    async def test_topic_subscriber_does_not_receive_other_topic_events(
        self, event_bus: EventBus
    ) -> None:
        """Test that a topic subscriber does not receive events for other topics."""
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        event_bus.subscribe(TestEvent, handler, topic="topic1")

        await event_bus.publish(TestEvent(message="for topic1"), topic="topic1")
        await event_bus.publish(TestEvent(message="for topic2"), topic="topic2")

        assert len(received) == 1
        assert received[0].message == "for topic1"

    @pytest.mark.asyncio
    async def test_broadcast_subscriber_receives_all_events(
        self, event_bus: EventBus
    ) -> None:
        """Test that a broadcast subscriber (topic=None) receives all events."""
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        # Subscribe without topic (broadcast)
        event_bus.subscribe(TestEvent, handler, topic=None)

        await event_bus.publish(TestEvent(message="topic1"), topic="topic1")
        await event_bus.publish(TestEvent(message="topic2"), topic="topic2")
        await event_bus.publish(TestEvent(message="no topic"), topic=None)

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_topic_and_broadcast_subscribers_both_receive(
        self, event_bus: EventBus
    ) -> None:
        """Test that both topic-specific and broadcast handlers receive events."""
        topic_received: list[TestEvent] = []
        broadcast_received: list[TestEvent] = []

        async def topic_handler(event: TestEvent) -> None:
            topic_received.append(event)

        async def broadcast_handler(event: TestEvent) -> None:
            broadcast_received.append(event)

        event_bus.subscribe(TestEvent, topic_handler, topic="topic1")
        event_bus.subscribe(TestEvent, broadcast_handler, topic=None)

        await event_bus.publish(TestEvent(message="hello"), topic="topic1")

        assert len(topic_received) == 1
        assert len(broadcast_received) == 1

    @pytest.mark.asyncio
    async def test_broadcast_publish_reaches_all_handlers(
        self, event_bus: EventBus
    ) -> None:
        """Test that publishing with topic=None reaches all handlers."""
        topic1_received: list[TestEvent] = []
        topic2_received: list[TestEvent] = []
        broadcast_received: list[TestEvent] = []

        async def topic1_handler(event: TestEvent) -> None:
            topic1_received.append(event)

        async def topic2_handler(event: TestEvent) -> None:
            topic2_received.append(event)

        async def broadcast_handler(event: TestEvent) -> None:
            broadcast_received.append(event)

        event_bus.subscribe(TestEvent, topic1_handler, topic="topic1")
        event_bus.subscribe(TestEvent, topic2_handler, topic="topic2")
        event_bus.subscribe(TestEvent, broadcast_handler, topic=None)

        # Publish without topic - should reach all handlers
        await event_bus.publish(TestEvent(message="broadcast"), topic=None)

        assert len(topic1_received) == 1
        assert len(topic2_received) == 1
        assert len(broadcast_received) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_with_topic(self, event_bus: EventBus) -> None:
        """Test that unsubscribe correctly removes topic-specific handler."""
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        event_bus.subscribe(TestEvent, handler, topic="topic1")
        await event_bus.publish(TestEvent(message="before"), topic="topic1")

        event_bus.unsubscribe(TestEvent, handler, topic="topic1")
        await event_bus.publish(TestEvent(message="after"), topic="topic1")

        assert len(received) == 1
        assert received[0].message == "before"

    @pytest.mark.asyncio
    async def test_has_subscribers_with_topic(self, event_bus: EventBus) -> None:
        """Test has_subscribers with topic filtering."""

        async def handler(event: TestEvent) -> None:
            pass

        # No subscribers initially
        assert not event_bus.has_subscribers(TestEvent, topic="topic1")
        assert not event_bus.has_subscribers(TestEvent, topic=None)

        # Subscribe to topic1
        event_bus.subscribe(TestEvent, handler, topic="topic1")

        # Should have subscribers for topic1
        assert event_bus.has_subscribers(TestEvent, topic="topic1")
        # Should also report subscribers when checking without topic filter
        assert event_bus.has_subscribers(TestEvent, topic=None)
        # Should not have subscribers for topic2
        assert not event_bus.has_subscribers(TestEvent, topic="topic2")

    @pytest.mark.asyncio
    async def test_publish_nowait_with_topic(self, event_bus: EventBus) -> None:
        """Test publish_nowait with topic support."""
        received: list[TestEvent] = []
        event = asyncio.Event()

        async def handler(evt: TestEvent) -> None:
            received.append(evt)
            event.set()

        event_bus.subscribe(TestEvent, handler, topic="topic1")

        await event_bus.publish_nowait(TestEvent(message="hello"), topic="topic1")

        # Wait for handler to be called
        await asyncio.wait_for(event.wait(), timeout=1.0)

        assert len(received) == 1
        assert received[0].message == "hello"

    @pytest.mark.asyncio
    async def test_event_inheritance_with_topics(self, event_bus: EventBus) -> None:
        """Test that event inheritance works with topics."""
        received: list[TestEvent] = []

        async def handler(event: TestEvent) -> None:
            received.append(event)

        # Subscribe to parent type
        event_bus.subscribe(TestEvent, handler, topic="topic1")

        # Publish child event
        await event_bus.publish(
            ChildEvent(message="child", extra="data"), topic="topic1"
        )

        assert len(received) == 1
        assert isinstance(received[0], ChildEvent)

    @pytest.mark.asyncio
    async def test_multiple_handlers_same_topic(self, event_bus: EventBus) -> None:
        """Test multiple handlers for the same topic."""
        received1: list[TestEvent] = []
        received2: list[TestEvent] = []

        async def handler1(event: TestEvent) -> None:
            received1.append(event)

        async def handler2(event: TestEvent) -> None:
            received2.append(event)

        event_bus.subscribe(TestEvent, handler1, topic="topic1")
        event_bus.subscribe(TestEvent, handler2, topic="topic1")

        await event_bus.publish(TestEvent(message="hello"), topic="topic1")

        assert len(received1) == 1
        assert len(received2) == 1

    @pytest.mark.asyncio
    async def test_api_url_as_topic(self, event_bus: EventBus) -> None:
        """Test using API URLs as topics (the primary use case)."""
        openai_received: list[TestEvent] = []
        anthropic_received: list[TestEvent] = []

        async def openai_handler(event: TestEvent) -> None:
            openai_received.append(event)

        async def anthropic_handler(event: TestEvent) -> None:
            anthropic_received.append(event)

        event_bus.subscribe(
            TestEvent, openai_handler, topic="https://api.openai.com/v1"
        )
        event_bus.subscribe(
            TestEvent, anthropic_handler, topic="https://api.anthropic.com"
        )

        await event_bus.publish(
            TestEvent(message="openai event"),
            topic="https://api.openai.com/v1",
        )
        await event_bus.publish(
            TestEvent(message="anthropic event"),
            topic="https://api.anthropic.com",
        )

        assert len(openai_received) == 1
        assert len(anthropic_received) == 1
        assert openai_received[0].message == "openai event"
        assert anthropic_received[0].message == "anthropic event"
