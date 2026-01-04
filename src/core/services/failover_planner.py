"""Failover plan selection and filtering service.

This service isolates failover planning logic including strategy selection,
health filtering, and circuit breaker integration.
"""

from __future__ import annotations

import logging

from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.services.failover_service import FailoverAttempt

logger = logging.getLogger(__name__)


class FailoverPlanner(IFailoverPlanner):
    """Planner for selecting and filtering failover plans.

    This implementation consolidates failover planning logic including:
    - Strategy vs coordinator selection
    - Health filtering for circuit breaker integration
    - Permanently disabled backend filtering
    - Fallback to original plan when all backends are filtered
    """

    def __init__(
        self,
        app_state: IApplicationState,
        failover_coordinator: IFailoverCoordinator,
        backend_lifecycle_manager: IBackendLifecycleManager,
        config: IConfig,
        failover_strategy: IFailoverStrategy | None = None,
        resilience_coordinator: IResilienceCoordinator | None = None,
    ):
        """Initialize the failover planner.

        Args:
            app_state: Application state for strategy enable/disable flag
            failover_coordinator: Coordinator for fallback failover planning
            backend_lifecycle_manager: Manager for backend lifecycle
            config: Application configuration
            failover_strategy: Optional strategy for advanced failover planning
            resilience_coordinator: Optional coordinator for resilience features
        """
        self._app_state = app_state
        self._failover_coordinator = failover_coordinator
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._config = config
        self._failover_strategy = failover_strategy
        self._resilience = resilience_coordinator

    def _normalize_plan(
        self, plan: list[FailoverAttempt] | list[tuple[str, str]]
    ) -> list[FailoverAttempt]:
        """Normalize plan to list of FailoverAttempt objects.

        Args:
            plan: Either a list of FailoverAttempt objects or tuples (backend, model)

        Returns:
            List of FailoverAttempt objects
        """
        if not plan:
            return []

        # Check if first item is already a FailoverAttempt
        if isinstance(plan[0], FailoverAttempt):
            return plan  # type: ignore[return-value]

        # Convert tuples to FailoverAttempt objects
        return [FailoverAttempt(backend=backend, model=model) for backend, model in plan]  # type: ignore[misc]

    def get_failover_plan(
        self, model: str, backend: str | None = None
    ) -> list[FailoverAttempt]:
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
            Ordered list of failover attempts to try
        """
        # Check if failover strategy is enabled
        use_strategy: bool = False
        try:
            use_strategy = self._app_state.get_use_failover_strategy()
        except (AttributeError, KeyError) as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not get failover strategy from app state: {e}",
                    exc_info=True,
                )
            use_strategy = False

        # Select plan source
        if use_strategy and self._failover_strategy is not None:
            try:
                # IFailoverStrategy requires non-None backend, use empty string as fallback
                backend_for_strategy = backend if backend is not None else ""
                plan = self._failover_strategy.get_failover_plan(
                    model, backend_for_strategy
                )
                # Convert tuples to FailoverAttempt objects if needed (for backward compatibility)
                normalized_plan = self._normalize_plan(plan)
                return self.filter_unhealthy_backends(normalized_plan)
            except (BackendError, RateLimitExceededError) as e:
                # Log debug info if strategy fails
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failover strategy failed: {e}", exc_info=True)
                # Fall back to coordinator attempts on error

        # Use coordinator as fallback or primary source
        # IFailoverCoordinator requires non-None backend, use empty string as fallback
        backend_for_coordinator = backend if backend is not None else ""
        attempts = self._failover_coordinator.get_failover_attempts(
            model, backend_for_coordinator
        )
        # Coordinator returns FailoverAttempt objects, no need to convert to tuples
        return self.filter_unhealthy_backends(attempts)

    def filter_unhealthy_backends(
        self, plan: list[FailoverAttempt]
    ) -> list[FailoverAttempt]:
        """Filter out backends with unhealthy API endpoints.

        Filtering logic:
        1. Check if circuit breaker is enabled in configuration
        2. Exclude permanently disabled backends
        3. Exclude unhealthy active backends (via backend.is_backend_functional())
        4. Fallback to original plan if all backends are filtered

        Args:
            plan: List of FailoverAttempt objects

        Returns:
            Filtered list excluding unhealthy backends (if circuit breaker enabled)
        """
        # Check if circuit breaker is enabled
        # Use getattr for defensive programming - test configs may not have health_check
        health_check = getattr(self._config, "health_check", None)
        if health_check is None or not getattr(
            health_check, "circuit_breaker_enabled", True
        ):
            return plan

        filtered: list[FailoverAttempt] = []
        disabled_backends = self._backend_lifecycle_manager.get_disabled_backends()
        active_backends = self._backend_lifecycle_manager.get_active_backends()

        for attempt in plan:
            backend_name = attempt.backend

            # Check permanently disabled registry first
            if backend_name in disabled_backends:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Skipping backend %s (permanently disabled: %s) in failover plan",
                        backend_name,
                        disabled_backends[backend_name].reason,
                    )
                continue

            backend = active_backends.get(backend_name)
            if backend is None:
                # Some backends are session-scoped and cached under keys like
                # "<backend>:<session_id>" or "<backend>:default". If we have an
                # active instance for the requested backend type, reuse it for
                # health filtering.
                backend = active_backends.get(f"{backend_name}:default")

            if backend is None:
                # Backend not yet created, include it (health unknown)
                filtered.append(attempt)
                continue

            if backend.is_backend_functional():
                filtered.append(attempt)
            else:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Skipping backend %s (unhealthy endpoint) in failover plan",
                        backend_name,
                    )

        if not filtered and plan:
            # If all backends were filtered out, return original plan
            # to avoid complete failure when health checks are too strict
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "All backends filtered as unhealthy, falling back to original plan"
                )
            return plan

        return filtered
