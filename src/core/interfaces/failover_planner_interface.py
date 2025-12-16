"""Interface for failover plan selection and filtering."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IFailoverPlanner(ABC):
    """Interface for selecting and filtering failover plans.

    This interface defines the contract for determining the ordered list of
    backend/model combinations to attempt when a request fails, including
    health filtering and circuit breaker integration.
    """

    @abstractmethod
    def get_failover_plan(
        self, model: str, backend: str | None = None
    ) -> list[tuple[str, str]]:
        """Select and filter failover plan for a request.

        This method:
        1. Selects failover plan via strategy (if enabled) or coordinator
        2. Filters out permanently disabled backends
        3. Filters out unhealthy backends (if circuit breaker enabled)
        4. Falls back to original plan if all backends are filtered

        Args:
            model: The requested model name
            backend: The original backend name (if known)

        Returns:
            Ordered list of (backend_name, model_name) tuples to attempt
        """

    @abstractmethod
    def filter_unhealthy_backends(
        self, plan: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Filter out backends with unhealthy API endpoints.

        Filtering logic:
        1. Check if circuit breaker is enabled in configuration
        2. Exclude permanently disabled backends
        3. Exclude unhealthy active backends (via backend.is_backend_functional())
        4. Fallback to original plan if all backends are filtered

        Args:
            plan: List of (backend, model) tuples

        Returns:
            Filtered list excluding unhealthy backends (if circuit breaker enabled)
        """
