"""Interface for the event bus (pub/sub pattern).

This module defines the abstract interface for a simple async event bus
that allows components to publish and subscribe to events in a decoupled manner.
Supports optional topic-based filtering for targeted event delivery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

# Event handler type: async callable that takes an event and returns None
EventHandler = Callable[[T], Coroutine[Any, Any, None]]


class IEventBus(ABC):
    """Interface for an asynchronous event bus.

    The event bus enables decoupled communication between components
    through a publish/subscribe pattern. Events are dispatched asynchronously
    to all registered handlers.

    Topic-based filtering:
    - Handlers can subscribe to specific topics (e.g., API URLs)
    - Events published with a topic only go to handlers for that topic
    - Handlers with topic=None receive ALL events (broadcast)
    - Topic=None when publishing sends to all handlers regardless of their topic
    """

    @abstractmethod
    def subscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
        topic: str | None = None,
    ) -> None:
        """Subscribe a handler to a specific event type, optionally filtered by topic.

        Args:
            event_type: The class of events to subscribe to.
            handler: An async callable that will be invoked when
                     events of the specified type are published.
            topic: Optional topic filter. If provided, the handler only receives
                   events published with this exact topic. If None, the handler
                   receives ALL events of the specified type (broadcast subscriber).
        """

    @abstractmethod
    def unsubscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
        topic: str | None = None,
    ) -> None:
        """Unsubscribe a handler from a specific event type and topic.

        Args:
            event_type: The class of events to unsubscribe from.
            handler: The handler to remove.
            topic: The topic the handler was subscribed to. Must match the
                   topic used when subscribing.
        """

    @abstractmethod
    async def publish(self, event: T, topic: str | None = None) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are invoked asynchronously. Errors in individual handlers
        do not prevent other handlers from being called.

        Args:
            event: The event instance to publish.
            topic: Optional topic for targeted delivery. If provided, only
                   handlers subscribed to this topic (plus broadcast handlers)
                   receive the event. If None, ALL handlers receive the event.
        """

    @abstractmethod
    async def publish_nowait(self, event: T, topic: str | None = None) -> None:
        """Publish an event without waiting for handlers to complete.

        This method schedules handlers to run but returns immediately.
        Useful for fire-and-forget event publishing where the publisher
        doesn't need to wait for handlers.

        Args:
            event: The event instance to publish.
            topic: Optional topic for targeted delivery.
        """

    @abstractmethod
    def has_subscribers(self, event_type: type[T], topic: str | None = None) -> bool:
        """Check if there are any subscribers for an event type.

        Args:
            event_type: The event class to check.
            topic: Optional topic to check. If None, checks for any subscribers
                   regardless of topic.

        Returns:
            True if at least one handler is subscribed.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shut down the event bus.

        Waits for pending event handlers to complete and clears all subscriptions.
        """
