from __future__ import annotations

from typing import Any

from src.core.interfaces.failover_interface import IFailoverCoordinator
from src.core.services.failover_service import FailoverAttempt, FailoverService


class FailoverCoordinator(IFailoverCoordinator):
    """Simple coordinator delegating to FailoverService.

    This object exists to decouple BackendService from the internal shape
    of the FailoverService and to provide a stable interface for tests.
    """

    def __init__(self, failover_service: FailoverService) -> None:
        self._svc = failover_service

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        # The FailoverService expects a BackendConfiguration-like object. The
        # service implementation in this codebase uses the `failover_routes`
        # attribute. We'll pass a simple adapter object that has a `failover_routes`
        # attribute to satisfy the method signature.
        class _Adapter:
            def __init__(self, routes: dict[str, Any]):
                # FailoverService expects a mapping keyed by model name to route
                # objects. Ensure we pass a dict[str, dict] shape.
                self.failover_routes: dict[str, dict[str, Any]] = routes

        adapter = _Adapter(dict(self._svc.failover_routes))
        return self._svc.get_failover_attempts(adapter, model, backend_type)

    def register_route(self, model: str, route: dict) -> None:
        # Route registration is handled on the underlying service.
        self._svc.failover_routes[model] = route
