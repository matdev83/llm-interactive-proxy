"""Backend availability checker collaborator."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.interfaces.backend_completion_collaborators import (
    IBackendAvailabilityChecker,
)
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import IResilienceCoordinator

logger = logging.getLogger(__name__)


class BackendAvailabilityChecker(IBackendAvailabilityChecker):
    """Checks backend availability using lifecycle manager and resilience coordinator."""

    def __init__(
        self,
        backend_lifecycle_manager: IBackendLifecycleManager,
        resilience_coordinator: IResilienceCoordinator | None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the availability checker.

        Args:
            backend_lifecycle_manager: Manager for backend lifecycle state
            resilience_coordinator: Coordinator for resilience decisions (circuit breakers, rate limits)
            failover_routes: Configuration of failover routes
        """
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._resilience = resilience_coordinator
        self._failover_routes = failover_routes or {}

    async def check_backend_availability(
        self, backend_type: str, effective_model: str, allow_failover: bool
    ) -> None:
        """Check if the backend is available (not disabled, not rate limited).

        Args:
            backend_type: The backend name
            effective_model: The model name
            allow_failover: Whether failover is allowed

        Raises:
            BackendError: If backend is permanently disabled
            RateLimitExceededError: If backend is rate limited
        """
        # Check if backend is permanently disabled
        disabled_info = self._backend_lifecycle_manager.get_disabled_backends().get(
            backend_type
        )
        if disabled_info and not (
            allow_failover
            and (
                effective_model in self._failover_routes
                or backend_type in self._failover_routes
            )
        ):
            raise BackendError(
                message=(
                    f"Backend {backend_type} is permanently disabled: "
                    f"{disabled_info.reason}"
                ),
                backend_name=backend_type,
            )

        # Check resilience coordinator for instance/model availability
        if self._resilience:
            decision = self._resilience.check_availability(
                backend_type, effective_model
            )
            if not decision.should_proceed():
                cooldown_info = (
                    f" (retry after {decision.cooldown_remaining:.1f}s)"
                    if decision.cooldown_remaining
                    else ""
                )
                raise RateLimitExceededError(
                    message=f"{decision.reason}{cooldown_info}",
                    reset_at=(
                        time.time() + decision.cooldown_remaining
                        if decision.cooldown_remaining
                        else None
                    ),
                )
