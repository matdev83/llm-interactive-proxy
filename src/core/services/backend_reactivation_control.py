"""Explicit control-plane contract for backend reactivation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.services.resilience.rate_limit_state import RateLimitStateManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendReactivationResult:
    """Outcome for explicit backend reactivation requests."""

    backend_instance: str
    lifecycle_reactivated: bool
    resilience_reactivated: bool
    unsupported_pairs_cleared: int = 0

    @property
    def reactivated(self) -> bool:
        return self.lifecycle_reactivated or self.resilience_reactivated


class BackendReactivationControl:
    """Coordinates explicit backend instance reactivation state transitions."""

    def __init__(
        self,
        *,
        backend_lifecycle_manager: IBackendLifecycleManager | None,
        resilience_coordinator: IResilienceCoordinator | None,
    ) -> None:
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._resilience_coordinator = resilience_coordinator

    def reactivate_backend_instance(
        self,
        backend_instance: str,
        *,
        clear_unsupported: bool = False,
    ) -> BackendReactivationResult:
        instance_id = backend_instance.strip()
        if not instance_id:
            raise ValueError("backend_instance must be a non-empty string")

        lifecycle_reactivated = False
        if self._backend_lifecycle_manager is not None and hasattr(
            self._backend_lifecycle_manager, "reactivate"
        ):
            lifecycle_reactivated = bool(
                self._backend_lifecycle_manager.reactivate(instance_id)  # type: ignore[attr-defined]
            )

        resilience_reactivated = False
        unsupported_pairs_cleared = 0
        state_manager = (
            getattr(self._resilience_coordinator, "state_manager", None)
            if self._resilience_coordinator is not None
            else None
        )
        if isinstance(state_manager, RateLimitStateManager):
            resilience_reactivated = state_manager.reactivate_instance(instance_id)
            if clear_unsupported:
                unsupported_pairs_cleared = (
                    state_manager.clear_unsupported_for_instance(instance_id)
                )

        result = BackendReactivationResult(
            backend_instance=instance_id,
            lifecycle_reactivated=lifecycle_reactivated,
            resilience_reactivated=resilience_reactivated,
            unsupported_pairs_cleared=unsupported_pairs_cleared,
        )
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Backend reactivation requested: instance=%s reactivated=%s lifecycle=%s resilience=%s unsupported_cleared=%d",
                instance_id,
                result.reactivated,
                lifecycle_reactivated,
                resilience_reactivated,
                unsupported_pairs_cleared,
            )
        return result
