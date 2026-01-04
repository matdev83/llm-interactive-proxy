from __future__ import annotations

from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.services.failover_service import FailoverAttempt


class DefaultFailoverStrategy(IFailoverStrategy):
    """Default strategy delegating to coordinator to compute attempts.

    Returns strongly-typed `FailoverAttempt` objects directly, avoiding
    unnecessary tuple conversion that loses field names.
    """

    def __init__(self, coordinator: IFailoverCoordinator) -> None:
        self._coordinator = coordinator

    def get_failover_plan(self, model: str, backend_type: str) -> list[FailoverAttempt]:
        attempts = self._coordinator.get_failover_attempts(model, backend_type)
        return attempts
