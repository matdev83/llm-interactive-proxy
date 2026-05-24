"""Model replacement cleanup End-of-Session subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
cleans up replacement service state when EoS is emitted, ensuring bounded memory usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.end_of_session_events import (
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.interfaces.model_replacement_service_interface import (
        IModelReplacementService,
    )

logger = logging.getLogger(__name__)


class ModelReplacementEosSubscriber:
    """Subscriber that cleans up replacement service state on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    calls ModelReplacementService.cleanup_session() to remove in-memory
    session state. Cleanup is best-effort and cannot block other
    subsystem finalization.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        replacement_service: IModelReplacementService,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            replacement_service: Replacement service for cleanup operations.
        """
        self._event_bus = event_bus
        self._replacement_service = replacement_service

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("ModelReplacementEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("ModelReplacementEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event by cleaning up replacement state.

        This method calls the replacement service's cleanup_session method
        to remove session state from _session_states and _disabled_sessions.
        Cleanup is best-effort and errors are logged but not propagated to
        avoid blocking other subscribers.

        Args:
            event: The EoS event containing session information.
        """
        try:
            session_id = event.session_id
            if not session_id:
                logger.debug("EoS event missing session_id, skipping cleanup")
                return

            # Cleanup replacement service state (best-effort)
            self._replacement_service.cleanup_session(session_id)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Cleaned up replacement service state for session %s",
                    session_id,
                )

        except Exception as e:
            # Best-effort: log but don't raise to avoid blocking other subscribers
            logger.warning(
                "Failed to cleanup replacement service state for EoS event (session_id=%s): %s",
                event.session_id,
                e,
                exc_info=True,
                extra={"session_id": event.session_id},
            )
