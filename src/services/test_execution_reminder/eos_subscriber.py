"""Test Execution Reminder End-of-Session event subscriber.

This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and emits
test execution reminders when sessions are in a dirty state (files modified
but tests not run).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.end_of_session_events import (
    RemoteBackendConnectionEndOfSessionEvent,
)

if TYPE_CHECKING:
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.services.test_execution_reminder.test_execution_reminder_handler import (
        TestExecutionReminderHandler,
    )

logger = logging.getLogger(__name__)


class TestExecutionReminderEosSubscriber:
    """Subscriber that emits test reminders on EoS events.

    This subscriber listens for RemoteBackendConnectionEndOfSessionEvent and
    checks if the session is in a dirty state. If so, it emits a steering
    reminder using the existing TestExecutionReminderHandler logic.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        reminder_handler: TestExecutionReminderHandler,
    ) -> None:
        """Initialize the subscriber.

        Args:
            event_bus: Event bus to subscribe to.
            reminder_handler: Test execution reminder handler for emitting reminders.
        """
        self._event_bus = event_bus
        self._reminder_handler = reminder_handler

    async def start(self) -> None:
        """Start the subscriber by subscribing to EoS events."""
        self._event_bus.subscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("TestExecutionReminderEosSubscriber subscribed to EoS events")

    async def stop(self) -> None:
        """Stop the subscriber by unsubscribing from EoS events."""
        self._event_bus.unsubscribe(
            RemoteBackendConnectionEndOfSessionEvent,
            self._handle_eos_event,
        )
        logger.debug("TestExecutionReminderEosSubscriber unsubscribed from EoS events")

    async def _handle_eos_event(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Handle an End-of-Session event.

        When EoS is reached and the session is in a dirty state (files modified
        but tests not run), this subscriber emits the configured reminder message
        by logging it prominently at WARNING level.

        Args:
            event: The EoS event containing session information.
        """
        try:
            # Check if session is dirty using reminder handler's state
            state = self._reminder_handler._get_session_state(event.session_id)
            if state and state.is_dirty:
                # Session is dirty - emit reminder notification per Requirement 7.4
                # Since the session has ended, we log the reminder prominently
                # rather than injecting it into the conversation stream
                reminder_message = getattr(self._reminder_handler, "_message", None)
                if reminder_message:
                    # Log at WARNING level to make it visible (Requirement 7.4)
                    logger.warning(
                        "EoS event for dirty session %s - test execution reminder: %s "
                        "(session ended with %d file modifications, tests not run)",
                        event.session_id,
                        reminder_message,
                        state.modification_count,
                        extra={
                            "session_id": event.session_id,
                            "modification_count": state.modification_count,
                            "reminder_message": reminder_message,
                        },
                    )
                else:
                    logger.warning(
                        "EoS event for dirty session %s - test execution reminder needed "
                        "(files modified but tests not run, %d modifications)",
                        event.session_id,
                        state.modification_count,
                        extra={
                            "session_id": event.session_id,
                            "modification_count": state.modification_count,
                        },
                    )
            else:
                logger.debug(
                    "EoS event for clean session %s - no reminder needed",
                    event.session_id,
                )
        except Exception as e:
            # Fail-open: log error but don't block other subscribers
            logger.exception(
                "Error handling EoS event for test reminder (session %s): %s",
                event.session_id,
                e,
                exc_info=True,
            )
