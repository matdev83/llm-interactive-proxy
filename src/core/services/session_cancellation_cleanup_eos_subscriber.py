"""Session cancellation cleanup End-of-Session subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
cleans up cancellation state when EoS is emitted, ensuring bounded memory usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.end_of_session_events import (
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.domain.session_key import SessionKey

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )

logger = logging.getLogger(__name__)


class SessionCancellationCleanupEosSubscriber:
    """Subscriber that cleans up cancellation state on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    calls SessionCancellationCoordinator.cleanup() to remove in-memory
    cancellation state. Cleanup is best-effort and cannot block other
    subsystem finalization.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        coordinator: ISessionCancellationCoordinator,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            coordinator: Cancellation coordinator for cleanup operations.
        """
        self._event_bus = event_bus
        self._coordinator = coordinator

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("SessionCancellationCleanupEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug(
            "SessionCancellationCleanupEosSubscriber unsubscribed from EoS events"
        )

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event by cleaning up cancellation state.

        This method derives a SessionKey from the event's session_id and calls
        the coordinator's cleanup method. Cleanup is best-effort and errors
        are logged but not propagated to avoid blocking other subscribers.

        Args:
            event: The EoS event containing session information.
        """
        try:
            # Derive SessionKey from session_id
            # For HTTP: session_id is the Trace ID (primary_id)
            # For Codebuff: session_id is codebuff:{id} (primary_id)
            # We need to infer protocol from session_id format
            session_id = event.session_id
            if not session_id:
                logger.debug("EoS event missing session_id, skipping cleanup")
                return

            # Determine transport protocol from session_id format
            # Note: event.protocol is the backend protocol (e.g., "openai"), not transport protocol
            # Transport protocol must be inferred from session_id format:
            # - Codebuff: session_id starts with "codebuff:"
            # - HTTP: all other cases (most common)
            if session_id.startswith("codebuff:"):
                protocol = "codebuff"
            else:
                # Assume HTTP (most common case)
                protocol = "http"

            primary_id = session_id
            # group_id is not available in EoS event, use None
            # This is acceptable as cleanup is keyed by primary_id for HTTP
            group_id = None

            session_key = SessionKey(
                protocol=protocol, primary_id=primary_id, group_id=group_id
            )

            # Cleanup cancellation state (best-effort)
            self._coordinator.cleanup(session_key)

        except Exception as e:
            # Best-effort: log but don't raise to avoid blocking other subscribers
            logger.warning(
                "Failed to cleanup cancellation state for EoS event (session_id=%s): %s",
                event.session_id,
                e,
                exc_info=True,
                extra={"session_id": event.session_id},
            )
