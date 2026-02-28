"""Redaction cache End-of-Session event subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and clears
redaction cache for the session to prevent memory leaks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.end_of_session_events import (
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.services.redaction_cache import RedactionCache

logger = logging.getLogger(__name__)


class RedactionCacheEosSubscriber:
    """Subscriber that clears redaction cache on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    calls RedactionCache.clear_session() to remove in-memory state.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        redaction_cache: RedactionCache,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            redaction_cache: Redaction cache to clear.
        """
        self._event_bus = event_bus
        self._redaction_cache = redaction_cache

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("RedactionCacheEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("RedactionCacheEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event by clearing redaction cache.

        Args:
            event: The EoS event containing session information.
        """
        try:
            session_id = event.session_id
            if not session_id:
                return

            self._redaction_cache.clear_session(session_id)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Cleared redaction cache for session %s on EoS",
                    session_id,
                )
        except Exception as e:
            # Fail-open: log error but don't block other subscribers
            logger.exception(
                "Error clearing redaction cache for session %s: %s",
                event.session_id,
                e,
                exc_info=True,
            )
