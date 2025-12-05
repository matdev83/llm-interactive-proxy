"""Health state manager for processing check events and emitting transitions.

This module provides the state management layer that:
- Subscribes to stateless health check events
- Updates endpoint health states
- Emits state transition events when health status changes
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.health_events import (
    EndpointHealthChanged,
    HttpCheckFailed,
    HttpCheckSucceeded,
    HttpHealthStateTransition,
    PingCheckFailed,
    PingCheckSucceeded,
    PingHealthStateTransition,
)
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.health.endpoint_registry import EndpointRegistry

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import HealthCheckConfig
    from src.core.domain.health.endpoint_health_state import EndpointHealthState

logger = logging.getLogger(__name__)


class HealthStateManager:
    """Manages health state transitions based on check events.

    This manager:
    - Subscribes to ping and HTTP check result events
    - Updates the corresponding EndpointHealthState
    - Emits state transition events when health status changes
    - Tracks failure thresholds to avoid false positives

    The manager acts as a stateful layer on top of the stateless check events,
    maintaining the current health status and deciding when to emit transitions.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        endpoint_registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> None:
        """Initialize the health state manager.

        Args:
            event_bus: Event bus for subscribing and publishing events.
            endpoint_registry: Registry containing health states.
            config: Health check configuration with thresholds.
        """
        self._event_bus = event_bus
        self._registry = endpoint_registry
        self._config = config
        self._subscribed = False

    async def start(self) -> None:
        """Start the state manager by subscribing to check events."""
        if self._subscribed:
            return

        # Subscribe to ping events
        self._event_bus.subscribe(PingCheckSucceeded, self._handle_ping_success)
        self._event_bus.subscribe(PingCheckFailed, self._handle_ping_failure)

        # Subscribe to HTTP events
        self._event_bus.subscribe(HttpCheckSucceeded, self._handle_http_success)
        self._event_bus.subscribe(HttpCheckFailed, self._handle_http_failure)

        self._subscribed = True
        logger.info("Health state manager started")

    async def stop(self) -> None:
        """Stop the state manager by unsubscribing from events."""
        if not self._subscribed:
            return

        # Unsubscribe from ping events
        self._event_bus.unsubscribe(PingCheckSucceeded, self._handle_ping_success)
        self._event_bus.unsubscribe(PingCheckFailed, self._handle_ping_failure)

        # Unsubscribe from HTTP events
        self._event_bus.unsubscribe(HttpCheckSucceeded, self._handle_http_success)
        self._event_bus.unsubscribe(HttpCheckFailed, self._handle_http_failure)

        self._subscribed = False
        logger.info("Health state manager stopped")

    async def _handle_ping_success(self, event: PingCheckSucceeded) -> None:
        """Handle a successful ping check event.

        Args:
            event: The ping success event.
        """
        state = self._registry.get_health_state(event.api_url)
        if state is None:
            logger.debug(
                "Ignoring ping success for unregistered URL: %s", event.api_url
            )
            return

        old_state = state.ping_check_success
        transitioned = state.record_ping_success(event.latency_ms)

        if transitioned:
            # State changed from unhealthy to healthy
            transition_event = PingHealthStateTransition(
                api_url=event.api_url,
                old_state=old_state,
                new_state=True,
                consecutive_failures=0,
            )
            await self._event_bus.publish(transition_event)
            logger.debug(
                "Ping state transition for %s: %s -> %s",
                event.api_url,
                old_state,
                True,
            )

            # Check if overall health changed
            await self._check_overall_health_change(event.api_url, state)

    async def _handle_ping_failure(self, event: PingCheckFailed) -> None:
        """Handle a failed ping check event.

        Args:
            event: The ping failure event.
        """
        state = self._registry.get_health_state(event.api_url)
        if state is None:
            logger.debug(
                "Ignoring ping failure for unregistered URL: %s", event.api_url
            )
            return

        old_state = state.ping_check_success
        threshold = self._config.ping.failure_threshold
        transitioned = state.record_ping_failure(event.error, threshold)

        if transitioned:
            # State changed from healthy to unhealthy
            transition_event = PingHealthStateTransition(
                api_url=event.api_url,
                old_state=old_state,
                new_state=False,
                consecutive_failures=state.consecutive_ping_failures,
            )
            await self._event_bus.publish(transition_event)
            logger.debug(
                "Ping state transition for %s: %s -> %s (failures: %d)",
                event.api_url,
                old_state,
                False,
                state.consecutive_ping_failures,
            )

            # Check if overall health changed
            await self._check_overall_health_change(event.api_url, state)

    async def _handle_http_success(self, event: HttpCheckSucceeded) -> None:
        """Handle a successful HTTP check event.

        Args:
            event: The HTTP success event.
        """
        state = self._registry.get_health_state(event.api_url)
        if state is None:
            logger.debug(
                "Ignoring HTTP success for unregistered URL: %s", event.api_url
            )
            return

        old_state = state.http_check_success
        transitioned = state.record_http_success(event.status_code, event.latency_ms)

        if transitioned:
            # State changed from unhealthy to healthy
            transition_event = HttpHealthStateTransition(
                api_url=event.api_url,
                old_state=old_state,
                new_state=True,
                consecutive_failures=0,
            )
            await self._event_bus.publish(transition_event)
            logger.debug(
                "HTTP state transition for %s: %s -> %s",
                event.api_url,
                old_state,
                True,
            )

            # Check if overall health changed
            await self._check_overall_health_change(event.api_url, state)

    async def _handle_http_failure(self, event: HttpCheckFailed) -> None:
        """Handle a failed HTTP check event.

        Args:
            event: The HTTP failure event.
        """
        state = self._registry.get_health_state(event.api_url)
        if state is None:
            logger.debug(
                "Ignoring HTTP failure for unregistered URL: %s", event.api_url
            )
            return

        old_state = state.http_check_success
        threshold = self._config.http.failure_threshold
        transitioned = state.record_http_failure(event.error, threshold)

        if transitioned:
            # State changed from healthy to unhealthy
            transition_event = HttpHealthStateTransition(
                api_url=event.api_url,
                old_state=old_state,
                new_state=False,
                consecutive_failures=state.consecutive_http_failures,
            )
            await self._event_bus.publish(transition_event)
            logger.debug(
                "HTTP state transition for %s: %s -> %s (failures: %d)",
                event.api_url,
                old_state,
                False,
                state.consecutive_http_failures,
            )

            # Check if overall health changed
            await self._check_overall_health_change(event.api_url, state)

    async def _check_overall_health_change(
        self,
        api_url: str,
        state: EndpointHealthState,
    ) -> None:
        """Check if overall endpoint health changed and emit event.

        This is called after any state transition to emit a combined
        health status event.

        Args:
            api_url: The API URL.
            state: The current health state.
        """

        # Emit combined health event
        event = EndpointHealthChanged(
            api_url=api_url,
            is_healthy=state.is_healthy,
            ping_healthy=state.ping_check_success,
            http_healthy=state.http_check_success,
        )
        await self._event_bus.publish(event)
