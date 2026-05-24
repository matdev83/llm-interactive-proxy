"""Wire Capture End-of-Session event subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and records
EoS metadata in wire capture records.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic.types import JsonValue

from src.core.domain.events.end_of_session_events import (
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


class WireCaptureEosSubscriber:
    """Subscriber that records EoS metadata in wire captures.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    records EoS occurrence and metadata in wire capture records.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        wire_capture: IWireCapture,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            wire_capture: Wire capture service for recording EoS metadata.
        """
        self._event_bus = event_bus
        self._wire_capture = wire_capture

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("WireCaptureEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("WireCaptureEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event.

        Args:
            event: The EoS event containing session information.
        """
        try:
            # Only record if wire capture is enabled
            if not self._wire_capture.enabled():
                return

            # Record EoS metadata in wire capture
            # Use capture_stream_completion method which accepts EoS metadata
            # Extract backend and model from backend field (format: "backend:model")
            backend = event.backend or "unknown"
            model = "unknown"
            if ":" in backend:
                backend, model = backend.split(":", 1)

            # Build EoS metadata dict (JSON-safe values only)
            eos_metadata: dict[str, JsonValue] = {
                "eos": True,
                "eos_signal": event.signal_type.value,
                "eos_reason": event.reason,
                "eos_termination_category": event.termination_category.value,
            }
            # Add error fields if this is an error termination
            if event.termination_category == EndOfSessionTerminationCategory.ERROR:
                eos_metadata["eos_error_classification"] = (
                    event.error_classification.value
                    if event.error_classification
                    else None
                )
                eos_metadata["eos_error_status_code"] = event.error_status_code

            await self._wire_capture.capture_stream_completion(
                context=None,  # Context not available in EoS event
                session_id=event.session_id,
                backend=backend,
                model=model,
                key_name=None,
                canonical_usage=None,  # EoS metadata is separate from usage
                eos_metadata=eos_metadata,
            )

            logger.debug(
                "Recorded EoS metadata in wire capture for session %s (signal: %s, reason: %s)",
                event.session_id,
                event.signal_type.value,
                event.reason,
            )
        except Exception as e:
            # Fail-open: log error but don't block other subscribers
            logger.exception(
                "Error handling EoS event for wire capture (session %s): %s",
                event.session_id,
                e,
                exc_info=True,
            )
