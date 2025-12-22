"""ProxyMem End-of-Session event subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and marks
ProxyMem sessions as complete, queuing them for analysis.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.end_of_session_events import (
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.interfaces.memory_service_interface import IMemoryService

logger = logging.getLogger(__name__)


class ProxyMemEosSubscriber:
    """Subscriber that marks ProxyMem sessions complete on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    calls MemoryService.mark_session_complete() to queue sessions for analysis.
    Idempotency is handled by MemoryService.mark_session_complete().
    """

    def __init__(
        self,
        event_bus: IEventBus,
        memory_service: IMemoryService,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            memory_service: Memory service for marking sessions complete.
        """
        self._event_bus = event_bus
        self._memory_service = memory_service

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("ProxyMemEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("ProxyMemEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event.

        Args:
            event: The EoS event containing session information.
        """
        try:
            # Check if memory is enabled for this session
            if not await self._memory_service.is_enabled_for_session(event.session_id):
                logger.debug(
                    "Memory not enabled for session %s, skipping EoS completion",
                    event.session_id,
                )
                return

            # Extract backend_model from backend field (format: "backend:model")
            backend_model = event.backend if event.backend else None

            # Extract termination reason from event (Requirement 5.3, 5.4)
            termination_reason = event.reason

            # Mark session complete (idempotency handled by MemoryService)
            await self._memory_service.mark_session_complete(
                event.session_id,
                backend_model=backend_model,
                termination_reason=termination_reason,
            )
            logger.debug(
                "Marked ProxyMem session %s complete (backend_model=%s, termination_reason=%s)",
                event.session_id,
                backend_model,
                termination_reason,
            )
        except Exception as e:
            # Fail-open: log error but don't block other subscribers
            logger.exception(
                "Error handling EoS event for ProxyMem session %s: %s",
                event.session_id,
                e,
                exc_info=True,
            )
