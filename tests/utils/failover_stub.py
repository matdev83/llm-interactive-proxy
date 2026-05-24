from __future__ import annotations

from typing import Any

from src.core.services.failover_service import FailoverAttempt


class StubFailoverCoordinator:
    """Minimal test stub for IFailoverCoordinator.

    - Returns configured attempts or a single attempt for the requested backend/model.
    - No-op register_route.
    """

    def __init__(self):
        self._configured_attempts: dict[str, list[FailoverAttempt]] = {}

    def configure_attempts(self, model: str, attempts: list[FailoverAttempt]) -> None:
        """Configure failover attempts for a specific model."""
        self._configured_attempts[model] = attempts

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        # Return configured attempts if available
        if model in self._configured_attempts:
            return self._configured_attempts[model]
        # Otherwise return a single attempt with the same backend/model
        return [FailoverAttempt(backend=backend_type, model=model)]

    def register_route(self, model: str, route: dict[str, Any]) -> None:
        return None
