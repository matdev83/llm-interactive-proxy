"""Backend health notifier service.

This service routes health state transition events to backend connector instances
that use the affected API URLs. It bridges the health check system with the
backend connectors through the event bus.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.domain.events.health_events import EndpointHealthChanged
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.interfaces.health_aware_interface import IHealthAware

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import HealthCheckConfig
    from src.core.services.health.endpoint_registry import EndpointRegistry

logger = logging.getLogger(__name__)


class BackendHealthNotifier:
    """Routes health state transition events to backend connector instances.

    This service:
    - Subscribes to EndpointHealthChanged events (the combined health status)
    - Looks up registered backends for the affected API URL
    - Notifies each backend by calling their IHealthAware methods

    The notification flow:
    1. HealthStateManager emits EndpointHealthChanged (combined ping + HTTP status)
    2. BackendHealthNotifier receives the event
    3. BackendHealthNotifier looks up backends using the API URL
    4. BackendHealthNotifier calls on_endpoint_healthy() or on_endpoint_unhealthy()
       on each backend

    Note: We only subscribe to EndpointHealthChanged (not individual PingHealthStateTransition
    or HttpHealthStateTransition) to avoid duplicate notifications. The combined event
    represents the overall endpoint health status which is what backends care about.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        endpoint_registry: EndpointRegistry,
        config: HealthCheckConfig,
    ) -> None:
        """Initialize the backend health notifier.

        Args:
            event_bus: The event bus to subscribe to events.
            endpoint_registry: Registry to look up backends for URLs.
            config: Health check configuration.
        """
        self._event_bus = event_bus
        self._endpoint_registry = endpoint_registry
        self._config = config
        self._is_started = False
        # Map of api_url -> set of IHealthAware backends
        self._backends: dict[str, set[IHealthAware]] = {}

    async def start(self) -> None:
        """Start listening for health state transition events."""
        if self._is_started:
            return

        if not self._config.notify_backends:
            logger.info(
                "Backend health notifications disabled by configuration, skipping."
            )
            return

        # Subscribe only to EndpointHealthChanged (combined status)
        # This avoids duplicate notifications from individual ping/HTTP transitions
        self._event_bus.subscribe(
            EndpointHealthChanged,
            self._handle_endpoint_health_changed,
        )

        self._is_started = True
        logger.info("BackendHealthNotifier started and subscribed to health events")

    async def stop(self) -> None:
        """Stop listening for health state transition events."""
        if not self._is_started:
            return

        self._event_bus.unsubscribe(
            EndpointHealthChanged,
            self._handle_endpoint_health_changed,
        )

        self._is_started = False
        logger.info("BackendHealthNotifier stopped")

    def register_backend(self, backend: IHealthAware) -> None:
        """Register a backend to receive health notifications.

        The backend will be notified when its API URL's health changes.

        Args:
            backend: A backend implementing IHealthAware interface.
        """
        api_url = backend.api_url
        if not api_url:
            logger.debug(
                "Backend has no api_url configured, skipping notification registration"
            )
            return

        # Normalize URL for consistent lookup
        normalized_url = self._endpoint_registry._normalize_url(api_url)

        if normalized_url not in self._backends:
            self._backends[normalized_url] = set()

        self._backends[normalized_url].add(backend)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Registered backend for health notifications: api_url=%s, "
                "total_backends_for_url=%d",
                normalized_url,
                len(self._backends[normalized_url]),
            )

    def unregister_backend(self, backend: IHealthAware) -> None:
        """Unregister a backend from health notifications.

        Args:
            backend: The backend to unregister.
        """
        api_url = backend.api_url
        if not api_url:
            return

        normalized_url = self._endpoint_registry._normalize_url(api_url)

        if normalized_url in self._backends:
            self._backends[normalized_url].discard(backend)
            if not self._backends[normalized_url]:
                del self._backends[normalized_url]

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Unregistered backend from health notifications: api_url=%s",
                    normalized_url,
                )

    def get_backends_for_url(self, api_url: str) -> set[IHealthAware]:
        """Get all registered backends for a given API URL.

        Args:
            api_url: The API URL to look up.

        Returns:
            Set of backends registered for this URL (may be empty).
        """
        normalized_url = self._endpoint_registry._normalize_url(api_url)
        return self._backends.get(normalized_url, set()).copy()

    async def _handle_endpoint_health_changed(
        self, event: EndpointHealthChanged
    ) -> None:
        """Handle overall endpoint health changed event.

        This provides a unified notification when the overall health status
        changes (combining ping and HTTP check results).

        Args:
            event: The endpoint health changed event.
        """
        reasons: list[str] = []
        if not event.ping_healthy:
            reasons.append("ping unhealthy")
        if not event.http_healthy:
            reasons.append("HTTP unhealthy")

        reason = ", ".join(reasons) if reasons else "recovered"

        await self._notify_backends(
            api_url=event.api_url,
            is_healthy=event.is_healthy,
            reason=reason,
        )

    async def _notify_backends(
        self,
        api_url: str,
        is_healthy: bool,
        reason: str,
    ) -> None:
        """Notify all backends registered for a URL about health change.

        Args:
            api_url: The API URL that changed health status.
            is_healthy: The new health status.
            reason: Human-readable reason for the change.
        """
        backends = self.get_backends_for_url(api_url)

        if not backends:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "No backends registered for health notifications: api_url=%s",
                    api_url,
                )
            return

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Notifying %d backends about health change: api_url=%s, healthy=%s",
                len(backends),
                api_url,
                is_healthy,
            )

        for backend in backends:
            try:
                if is_healthy:
                    await backend.on_endpoint_healthy(api_url)
                else:
                    await backend.on_endpoint_unhealthy(api_url, reason)
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                # Expected exceptions from backend notification methods (runtime errors, argument/type errors)
                # Log with full context and continue to notify other backends
                logger.exception(
                    "Error notifying backend about health change: api_url=%s, backend_type=%s",
                    api_url,
                    type(backend).__name__,
                )
            except Exception as exc:
                # Unexpected errors during backend notification (defensive guard)
                # Log with full context and continue to notify other backends
                logger.exception(
                    "Unexpected error notifying backend about health change: api_url=%s, backend_type=%s",
                    api_url,
                    type(backend).__name__,
                )
