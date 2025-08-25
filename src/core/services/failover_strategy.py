from __future__ import annotations

from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)


class DefaultFailoverStrategy(IFailoverStrategy):
    """Default strategy delegating to the coordinator to compute attempts.

    Adapter to expose a stable `(backend, model)` plan surface without coupling
    callers to `FailoverAttempt` internals.
    """

    def __init__(self, coordinator: IFailoverCoordinator) -> None:
        self._coordinator = coordinator

    def get_failover_plan(self, model: str, backend_type: str) -> list[tuple[str, str]]:
        attempts = self._coordinator.get_failover_attempts(model, backend_type)
        return [(a.backend, a.model) for a in attempts]
