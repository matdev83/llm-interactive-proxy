from __future__ import annotations

from typing import Any

from src.core.services.failover_service import FailoverAttempt


class StubFailoverCoordinator:
    """Minimal test stub for IFailoverCoordinator.

    - Returns a single attempt for the requested backend/model.
    - No-op register_route.
    """

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        return [FailoverAttempt(backend=backend_type, model=model)]

    def register_route(self, model: str, route: dict[str, Any]) -> None:
        return None
