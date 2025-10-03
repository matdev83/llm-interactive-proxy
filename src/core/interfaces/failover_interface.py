from __future__ import annotations

from typing import Protocol

from src.core.services.failover_service import FailoverAttempt


class IFailoverCoordinator(Protocol):
    """Interface for coordinating failover attempts and policies."""

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        """Return ordered failover attempts for given model and backend."""

    def register_route(self, model: str, route: dict) -> None:
        """Register or update a failover route."""


class IFailoverStrategy(Protocol):
    """Strategy interface for determining failover attempts.

    This formalizes the decision policy independently from concrete services.
    """

    def get_failover_plan(self, model: str, backend_type: str) -> list[tuple[str, str]]:
        """Return ordered (backend, model) pairs to attempt for a request."""
