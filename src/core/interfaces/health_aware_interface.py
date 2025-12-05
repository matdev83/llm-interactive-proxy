"""Interface for health-aware components.

This module defines the protocol for components (like backend connectors)
that need to react to API endpoint health state changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IHealthAware(Protocol):
    """Protocol for components that react to API endpoint health changes.

    Components implementing this interface will be notified when the health
    state of their API endpoint changes. This enables:
    - Circuit breaker patterns (auto-disable on health degradation)
    - Logging and observability
    - Automatic recovery when health is restored

    The api_url property identifies which endpoint this component uses,
    allowing the health notification system to route events correctly.
    """

    @property
    def api_url(self) -> str | None:
        """The API URL this component is associated with.

        Returns:
            The API endpoint URL, or None if not configured.
        """
        ...

    @property
    def is_endpoint_healthy(self) -> bool:
        """Current health status of the backend's API endpoint.

        Returns:
            True if the endpoint is considered healthy.
        """
        ...

    async def on_endpoint_healthy(self, api_url: str) -> None:
        """Called when the API endpoint becomes healthy (recovery).

        This is invoked when the endpoint transitions from unhealthy to healthy,
        either for ping checks, HTTP checks, or overall health.

        Args:
            api_url: The API URL that became healthy.
        """
        ...

    async def on_endpoint_unhealthy(self, api_url: str, reason: str) -> None:
        """Called when the API endpoint becomes unhealthy (degradation).

        This is invoked when the endpoint transitions from healthy to unhealthy.
        The component should update its internal state and may choose to:
        - Mark itself as non-functional
        - Log a warning
        - Trigger circuit breaker logic

        Args:
            api_url: The API URL that became unhealthy.
            reason: Human-readable reason for the health degradation
                    (e.g., "ping check failed", "HTTP timeout").
        """
        ...
