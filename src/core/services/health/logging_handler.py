"""Logging handler for health state transition events.

This module provides an event handler that logs health state transitions
at the WARNING level to alert operators about backend health changes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.health_events import (
    EndpointHealthChanged,
    HttpHealthStateTransition,
    PingHealthStateTransition,
)
from src.core.interfaces.event_bus_interface import IEventBus

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import HealthCheckConfig

logger = logging.getLogger(__name__)


class HealthLoggingHandler:
    """Logs health state transitions at WARNING level.

    This handler subscribes to state transition events and emits
    WARNING-level log messages when backend health status changes.

    Log levels:
    - WARNING: State transitions (both healthy->unhealthy and unhealthy->healthy)
    - INFO: Healthy transitions (recovery) if verbose logging enabled
    - DEBUG: Detailed health check information
    """

    def __init__(
        self,
        event_bus: IEventBus,
        config: HealthCheckConfig,
    ) -> None:
        """Initialize the logging handler.

        Args:
            event_bus: Event bus for subscribing to events.
            config: Health check configuration.
        """
        self._event_bus = event_bus
        self._config = config
        self._subscribed = False

    async def start(self) -> None:
        """Start the logging handler by subscribing to events."""
        if self._subscribed:
            return

        # Subscribe to state transition events
        self._event_bus.subscribe(
            PingHealthStateTransition, self._handle_ping_transition
        )
        self._event_bus.subscribe(
            HttpHealthStateTransition, self._handle_http_transition
        )
        self._event_bus.subscribe(
            EndpointHealthChanged, self._handle_endpoint_health_changed
        )

        self._subscribed = True
        logger.debug("Health logging handler started")

    async def stop(self) -> None:
        """Stop the logging handler by unsubscribing from events."""
        if not self._subscribed:
            return

        self._event_bus.unsubscribe(
            PingHealthStateTransition, self._handle_ping_transition
        )
        self._event_bus.unsubscribe(
            HttpHealthStateTransition, self._handle_http_transition
        )
        self._event_bus.unsubscribe(
            EndpointHealthChanged, self._handle_endpoint_health_changed
        )

        self._subscribed = False
        logger.debug("Health logging handler stopped")

    async def _handle_ping_transition(self, event: PingHealthStateTransition) -> None:
        """Handle ping health state transition events.

        Args:
            event: The ping state transition event.
        """
        if event.new_state:
            # Transition to healthy (recovery)
            logger.warning(
                "PING HEALTH RECOVERED: Backend endpoint %s is now reachable via ICMP ping",
                event.api_url,
            )
        else:
            # Transition to unhealthy
            logger.warning(
                "PING HEALTH FAILED: Backend endpoint %s is unreachable via ICMP ping "
                "(consecutive failures: %d)",
                event.api_url,
                event.consecutive_failures,
            )

    async def _handle_http_transition(self, event: HttpHealthStateTransition) -> None:
        """Handle HTTP health state transition events.

        Args:
            event: The HTTP state transition event.
        """
        if event.new_state:
            # Transition to healthy (recovery)
            logger.warning(
                "HTTP HEALTH RECOVERED: Backend endpoint %s is now responding to HTTP requests",
                event.api_url,
            )
        else:
            # Transition to unhealthy
            logger.warning(
                "HTTP HEALTH FAILED: Backend endpoint %s is not responding to HTTP requests "
                "(consecutive failures: %d)",
                event.api_url,
                event.consecutive_failures,
            )

    async def _handle_endpoint_health_changed(
        self, event: EndpointHealthChanged
    ) -> None:
        """Handle overall endpoint health change events.

        Args:
            event: The endpoint health changed event.
        """
        if event.is_healthy:
            logger.warning(
                "ENDPOINT HEALTHY: Backend %s is fully operational "
                "(ping: %s, http: %s)",
                event.api_url,
                "OK" if event.ping_healthy else "FAIL",
                "OK" if event.http_healthy else "FAIL",
            )
        else:
            logger.warning(
                "ENDPOINT UNHEALTHY: Backend %s has health issues "
                "(ping: %s, http: %s)",
                event.api_url,
                "OK" if event.ping_healthy else "FAIL",
                "OK" if event.http_healthy else "FAIL",
            )
