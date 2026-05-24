"""Async event bus implementation.

This module provides a simple but robust async event bus for the pub/sub pattern.
It allows components to communicate in a decoupled manner through events.
Supports topic-based filtering for targeted event delivery.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar
from weakref import WeakSet

from src.core.interfaces.event_bus_interface import IEventBus

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Event handler type
EventHandler = Callable[[T], Coroutine[Any, Any, None]]

# Sentinel for broadcast topic (handlers that receive all events)
_BROADCAST_TOPIC = None

# Maximum number of handlers to prevent unbounded memory growth
# This limit prevents memory leaks when handlers are dynamically subscribed
# but never unsubscribed.
_MAX_TOTAL_HANDLERS = 10000


class EventBus(IEventBus):
    """Asynchronous event bus implementation with topic support.

    This event bus provides a pub/sub mechanism where:
    - Handlers are invoked concurrently for each published event
    - Errors in one handler don't affect other handlers
    - Events can be published with or without waiting for completion
    - Topic-based filtering allows targeted event delivery

    Topic behavior:
    - subscribe(event_type, handler, topic="api.openai.com") - only gets events
      published with that exact topic
    - subscribe(event_type, handler, topic=None) - gets ALL events (broadcast)
    - publish(event, topic="api.openai.com") - goes to topic handlers + broadcast
    - publish(event, topic=None) - goes to ALL handlers
    """

    def __init__(self, max_total_handlers: int = _MAX_TOTAL_HANDLERS) -> None:
        """Initialize the event bus.

        Args:
            max_total_handlers: Maximum total number of handlers across all event types
                               and topics. Prevents unbounded memory growth when handlers
                               are dynamically subscribed but never unsubscribed.
                               Default: 10000
        """
        # Structure: event_type -> topic -> list of handlers
        # topic=None is used for broadcast handlers
        self._handlers: dict[type, dict[str | None, list[EventHandler[Any]]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        self._pending_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()
        self._lock = threading.Lock()
        self._shutting_down = False
        self._max_total_handlers = max_total_handlers

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
                     events of specified type are published.
            topic: Optional topic for targeted delivery. If None, handler
                  receives ALL events of the specified type (broadcast).
        """
        if self._shutting_down:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Attempted to subscribe handler during shutdown: %s for %s",
                    handler,
                    event_type.__name__,
                )
            return

        with self._lock:
            # Check total handler count before adding
            total_handlers = sum(
                len(handlers)
                for topic_map in self._handlers.values()
                for handlers in topic_map.values()
            )

            if total_handlers >= self._max_total_handlers:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Cannot subscribe handler: max_total_handlers (%d) reached. "
                        "Handler accumulation detected - consider unsubscribing unused handlers.",
                        self._max_total_handlers,
                    )
                return

            topic_handlers = self._handlers[event_type][topic]
            if handler not in topic_handlers:
                topic_handlers.append(handler)
                if logger.isEnabledFor(logging.DEBUG):
                    handler_name = (
                        handler.__name__ if hasattr(handler, "__name__") else handler
                    )
                    topic_str = f"topic={topic}" if topic else "broadcast"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Subscribed handler %s to event type %s (%s)",
                            handler_name,
                            event_type.__name__,
                            topic_str,
                        )

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
            topic: The topic the handler was subscribed to.
        """
        with self._lock:
            try:
                self._handlers[event_type][topic].remove(handler)
                if logger.isEnabledFor(logging.DEBUG):
                    handler_name = (
                        handler.__name__ if hasattr(handler, "__name__") else handler
                    )
                    topic_str = f"topic={topic}" if topic else "broadcast"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Unsubscribed handler %s from event type %s (%s)",
                            handler_name,
                            event_type.__name__,
                            topic_str,
                        )
            except ValueError:
                if logger.isEnabledFor(logging.DEBUG):
                    handler_name = (
                        handler.__name__ if hasattr(handler, "__name__") else handler
                    )
                    topic_str = f"topic={topic}" if topic else "broadcast"
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Handler %s was not subscribed to %s (%s)",
                            handler_name,
                            event_type.__name__,
                            topic_str,
                        )

    async def publish(self, event: object, topic: str | None = None) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are invoked concurrently. Errors in individual handlers
        are logged but don't prevent other handlers from being called.

        Args:
            event: The event instance to publish.
            topic: Optional topic for targeted delivery.
        """
        if self._shutting_down:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Attempted to publish event during shutdown: %s",
                    type(event).__name__,
                )
            return

        event_type = type(event)
        handlers = self._get_handlers_for_event(event_type, topic)

        if not handlers:
            if logger.isEnabledFor(logging.DEBUG):
                topic_str = f"topic={topic}" if topic else "broadcast"
                logger.debug(
                    "No handlers for event type %s (%s)",
                    event_type.__name__,
                    topic_str,
                )
            return

        # Invoke all handlers concurrently
        tasks = [
            asyncio.create_task(self._invoke_handler(handler, event))
            for handler in handlers
        ]

        if tasks:
            # Wait for all handlers to complete
            await asyncio.gather(*tasks, return_exceptions=True)

    async def publish_nowait(self, event: object, topic: str | None = None) -> None:
        """Publish an event without waiting for handlers to complete.

        This method schedules handlers to run but returns immediately.

        Args:
            event: The event instance to publish.
            topic: Optional topic for targeted delivery.
        """
        if self._shutting_down:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Attempted to publish_nowait during shutdown: %s",
                    type(event).__name__,
                )
            return

        event_type = type(event)
        handlers = self._get_handlers_for_event(event_type, topic)

        if not handlers:
            if logger.isEnabledFor(logging.DEBUG):
                topic_str = f"topic={topic}" if topic else "broadcast"
                logger.debug(
                    "No handlers for event type %s (%s)",
                    event_type.__name__,
                    topic_str,
                )
            return

        # Schedule handlers without waiting
        for handler in handlers:
            task = asyncio.create_task(self._invoke_handler(handler, event))
            with self._lock:
                self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks_discard)

    def _pending_tasks_discard(self, task: asyncio.Task[Any]) -> None:
        """Discard a pending task in a thread-safe manner."""
        with self._lock:
            self._pending_tasks.discard(task)

    def _get_handlers_for_event(
        self, event_type: type, topic: str | None = None
    ) -> list[EventHandler[Any]]:
        """Get all handlers for an event type and topic.

        Args:
            event_type: The event class.
            topic: The topic to match. If provided, returns handlers for that
                   topic plus broadcast handlers. If None, returns all handlers.

        Returns:
            List of handlers that should receive the event.

        Thread-safety: Acquires lock to read _handlers while preventing
        concurrent modifications by subscribe/unsubscribe. Returns a copy
        of the handlers list to avoid holding lock during handler invocation.
        """
        with self._lock:
            handlers: list[EventHandler[Any]] = []

            # Get handlers for exact type and all parent types
            for registered_type, topic_map in self._handlers.items():
                if issubclass(event_type, registered_type):
                    if topic is not None:
                        # Specific topic: get topic handlers + broadcast handlers
                        handlers.extend(topic_map.get(topic, []))
                        handlers.extend(topic_map.get(_BROADCAST_TOPIC, []))
                    else:
                        # No topic (broadcast publish): get ALL handlers
                        for topic_handlers in topic_map.values():
                            handlers.extend(topic_handlers)

            return handlers[:]  # Return a copy to avoid concurrent modification

    async def _invoke_handler(
        self,
        handler: EventHandler[Any],
        event: Any,
    ) -> None:
        """Safely invoke a single handler with an event.

        Args:
            handler: The handler to invoke.
            event: The event to pass to the handler.
        """
        handler_name = (
            handler.__name__ if hasattr(handler, "__name__") else str(handler)
        )
        try:
            await handler(event)
        except asyncio.CancelledError:
            # Let cancellation propagate - handler cancellation is intentional
            raise
        except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
            # Common handler errors - log with full context
            log_extra = {}
            log_message = "Error in event handler %s for event %s: %s"
            log_args = [handler_name, type(event).__name__, type(exc).__name__]

            # Add session_id correlation for RemoteBackendConnectionEndOfSessionEvent
            try:
                from src.core.domain.events.end_of_session_events import (
                    RemoteBackendConnectionEndOfSessionEvent,
                )

                if isinstance(event, RemoteBackendConnectionEndOfSessionEvent):
                    session_id = getattr(event, "session_id", None)
                    if session_id:
                        log_extra["session_id"] = session_id
                        log_message += " (session_id=%s)"
                        log_args.append(session_id)
            except ImportError:
                # EoS events module not available, skip correlation
                pass

            logger.exception(
                log_message,
                *log_args,
                extra=log_extra if log_extra else None,
            )
        except Exception as exc:
            # Catch-all for other unexpected exceptions
            # Extract correlation identifiers for EoS events
            log_extra = {}
            log_message = "Error in event handler %s for event %s: %s"
            log_args = [handler_name, type(event).__name__, type(exc).__name__]

            # Add session_id correlation for RemoteBackendConnectionEndOfSessionEvent
            try:
                from src.core.domain.events.end_of_session_events import (
                    RemoteBackendConnectionEndOfSessionEvent,
                )

                if isinstance(event, RemoteBackendConnectionEndOfSessionEvent):
                    session_id = getattr(event, "session_id", None)
                    if session_id:
                        log_extra["session_id"] = session_id
                        log_message += " (session_id=%s)"
                        log_args.append(session_id)
            except ImportError:
                # EoS events module not available, skip correlation
                pass

            logger.exception(
                log_message,
                *log_args,
                extra=log_extra if log_extra else None,
            )

    def _count_total_handlers(self) -> int:
        """Count total number of handlers across all event types and topics.

        Returns:
            Total number of handlers registered.
        """
        return sum(
            len(handlers)
            for topic_map in self._handlers.values()
            for handlers in topic_map.values()
        )

    def has_subscribers(self, event_type: type[T], topic: str | None = None) -> bool:
        """Check if there are any subscribers for an event type.

        Args:
            event_type: The event class to check.
            topic: Optional topic to check. If None, checks for any subscribers.

        Returns:
            True if at least one handler is subscribed.
        """
        topic_map = self._handlers.get(event_type)
        if not topic_map:
            return False

        if topic is not None:
            # Check specific topic + broadcast
            return bool(topic_map.get(topic)) or bool(topic_map.get(_BROADCAST_TOPIC))
        else:
            # Check any handlers exist
            return any(handlers for handlers in topic_map.values())

    async def shutdown(self) -> None:
        """Gracefully shut down the event bus.

        Waits for pending event handlers to complete and clears all subscriptions.
        """
        self._shutting_down = True

        # Wait for any pending tasks with timeout
        with self._lock:
            pending = [t for t in self._pending_tasks if not t.done()]
        if pending:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Waiting for %d pending event handlers to complete", len(pending)
                )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Timeout waiting for event handlers, cancelling", exc_info=True
                    )
                for task in pending:
                    if not task.done():
                        task.cancel()

        # Clear all handlers
        with self._lock:
            self._handlers.clear()
            self._pending_tasks.clear()

        if logger.isEnabledFor(logging.INFO):
            logger.info("Event bus shutdown complete")
