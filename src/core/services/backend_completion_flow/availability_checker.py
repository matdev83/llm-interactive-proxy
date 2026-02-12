"""Backend availability checker collaborator."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.common.exceptions import (
    RateLimitExceededError,
    RoutingError,
    ServiceUnavailableError,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_completion_collaborators import (
    IBackendAvailabilityChecker,
)
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.services.resilience.scope import build_resilience_instance_id

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
        self,
        backend_type: str,
        effective_model: str,
        allow_failover: bool,
        context: RequestContext | None = None,
    ) -> None:
        """Check if the backend is available (not disabled, not rate limited).

        Args:
            backend_type: The backend name
            effective_model: The model name
            allow_failover: Whether failover is allowed

        Raises:
            ServiceUnavailableError: If backend is permanently disabled
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
            raise ServiceUnavailableError(
                message=(
                    f"Backend {backend_type} is permanently disabled: "
                    f"{disabled_info.reason}"
                ),
                details={"backend": backend_type, "reason": disabled_info.reason},
            )

        # Check resilience coordinator for instance/model availability
        if self._resilience:
            instance_id = build_resilience_instance_id(backend_type, context)
            decision = self._resilience.check_availability(instance_id, effective_model)
            if not decision.should_proceed():
                normalized_reason = decision.reason.lower()
                if "unsupported" in normalized_reason:
                    raise RoutingError(
                        message=decision.reason
                        or "Model unsupported on selected backend",
                        details={
                            "code": "unsupported_on_instance",
                            "category": "availability",
                            "retryable": False,
                            "backend_type": backend_type,
                            "model": effective_model,
                            "reason": decision.reason,
                        },
                    )

                if "disabled" in normalized_reason and not decision.cooldown_remaining:
                    raise ServiceUnavailableError(
                        message=decision.reason or "Backend instance disabled",
                        details={"backend": backend_type, "reason": decision.reason},
                    )

                cooldown_info = (
                    f" (retry after {decision.cooldown_remaining:.1f}s)"
                    if decision.cooldown_remaining
                    else ""
                )
                if decision.cooldown_remaining:
                    raise RateLimitExceededError(
                        message=f"{decision.reason}{cooldown_info}",
                        details={
                            "code": "temporarily_unavailable",
                            "category": "availability",
                            "retryable": True,
                            "backend_type": backend_type,
                            "model": effective_model,
                            "reason": decision.reason,
                        },
                        reset_at=time.time() + decision.cooldown_remaining,
                    )

                raise RoutingError(
                    message=decision.reason or "Backend temporarily unavailable",
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "backend_type": backend_type,
                        "model": effective_model,
                        "reason": decision.reason,
                    },
                )
