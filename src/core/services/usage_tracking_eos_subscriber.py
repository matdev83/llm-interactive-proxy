"""Usage Tracking End-of-Session event subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and updates
session metrics to mark sessions as complete and record EoS metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.core.database.models.usage import SessionMetricsTable
from src.core.domain.events.end_of_session_events import (
    EndOfSessionTerminationCategory,
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.database.repositories.usage_repository import SessionMetricsRepository
    from src.core.interfaces.event_bus_interface import IEventBus

logger = logging.getLogger(__name__)


class UsageTrackingEosSubscriber:
    """Subscriber that updates session metrics on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    updates SessionMetricsTable to mark sessions as complete and record EoS
    metadata (timestamp, signal type, reason).
    """

    def __init__(
        self,
        event_bus: IEventBus,
        session_repository: SessionMetricsRepository,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            session_repository: Repository for updating session metrics.
        """
        self._event_bus = event_bus
        self._session_repository = session_repository

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("UsageTrackingEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("UsageTrackingEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event.

        Args:
            event: The EoS event containing session information.
        """
        try:
            # Get existing metrics or create new ones
            existing = await self._session_repository.get_by_id(event.session_id)
            # Use event timestamp to maintain consistency with claim_eos_emission timestamp
            # The claim already sets eos_emitted_at, but we may need to update error fields
            event_timestamp = event.timestamp
            now = datetime.now(timezone.utc)

            if existing:
                # Update existing metrics with EoS data only
                # Preserve all other fields (turn_count, total_tokens, etc.)
                # Note: eos_emitted_at, eos_signal_type, and eos_reason are already set by
                # claim_eos_emission(), but we update them here to ensure consistency and
                # to handle the case where the subscriber runs before the claim completes.
                # Use event.timestamp to maintain consistency with the claim timestamp.
                existing.is_completed = True
                existing.eos_emitted_at = event_timestamp
                existing.eos_signal_type = event.signal_type.value
                existing.eos_reason = event.reason
                existing.last_activity = now
                # Set error fields if this is an error termination
                # These fields are NOT set by claim_eos_emission(), so we must set them here
                if event.termination_category == EndOfSessionTerminationCategory.ERROR:
                    existing.eos_error_classification = (
                        event.error_classification.value
                        if event.error_classification
                        else None
                    )
                    existing.eos_error_status_code = event.error_status_code
                else:
                    # Clear error fields for normal terminations
                    existing.eos_error_classification = None
                    existing.eos_error_status_code = None
                # Use update instead of upsert to avoid overwriting fields
                await self._session_repository.update(existing)
            else:
                # Create new metrics with EoS data
                # This case is rare since claim_eos_emission() requires existing metrics,
                # but we handle it for completeness
                metrics = SessionMetricsTable(
                    session_id=event.session_id,
                    start_time=event_timestamp,
                    last_activity=now,
                    turn_count=0,
                    total_tokens=0,
                    total_tool_calls=0,
                    is_completed=True,
                    eos_emitted_at=event_timestamp,
                    eos_signal_type=event.signal_type.value,
                    eos_reason=event.reason,
                    # Set error fields if this is an error termination
                    eos_error_classification=(
                        event.error_classification.value
                        if event.termination_category
                        == EndOfSessionTerminationCategory.ERROR
                        and event.error_classification
                        else None
                    ),
                    eos_error_status_code=(
                        event.error_status_code
                        if event.termination_category
                        == EndOfSessionTerminationCategory.ERROR
                        else None
                    ),
                )
                await self._session_repository.create(metrics)

            logger.debug(
                "Updated session metrics for session %s (EoS: %s, reason: %s)",
                event.session_id,
                event.signal_type.value,
                event.reason,
            )
        except Exception as e:
            # Fail-open: log error but don't block other subscribers
            logger.exception(
                "Error handling EoS event for usage tracking (session %s): %s",
                event.session_id,
                e,
                exc_info=True,
            )
