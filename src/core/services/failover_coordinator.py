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
        # First, check for a direct backend-level failover mapping such as
        # {"openai": "anthropic"}. These routes simply swap the backend while
        # reusing the same model name.
        direct_route = self._svc.get_failover_route(backend_type)
        if isinstance(direct_route, str) and direct_route:
            return [FailoverAttempt(backend=direct_route, model=model)]

        # Normalize any structured route definitions (policy/elements) so they
        # can be consumed by FailoverService.get_failover_attempts, which expects
        # a BackendConfiguration-like object exposing ``failover_routes`` keyed by
        # model name.
        normalized_routes = self._normalize_routes(direct_route, model)
        if not normalized_routes:
            # Fall back to the raw failover_routes mapping maintained by the
            # service. This may already be keyed by model name when populated
            # from backend configuration objects.
            normalized_routes = self._normalize_routes(
                self._svc.failover_routes, model
            )

        if not normalized_routes:
            return []

        class _Adapter:
            def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
                self.failover_routes = routes

        return self._svc.get_failover_attempts(_Adapter(normalized_routes), model, backend_type)

    def register_route(self, model: str, route: dict) -> None:
        # Route registration is handled on the underlying service.
        self._svc.failover_routes[model] = route

    def _normalize_routes(
        self, raw_routes: Any, model: str
    ) -> dict[str, dict[str, Any]] | None:
        if not isinstance(raw_routes, dict):
            return None

        # If the dictionary already looks like {model: {...}}, extract the
        # requested model entry when present.
        if model in raw_routes and isinstance(raw_routes[model], dict):
            return {model: raw_routes[model]}

        # Handle dictionaries that represent a single route definition with
        # policy/elements keys (e.g., {"policy": "k", "elements": [...]}) by
        # wrapping them under the requested model name.
        if {"policy", "elements"}.intersection(raw_routes.keys()):
            return {model: raw_routes}

        # In some scenarios the mapping may already be keyed by multiple models;
        # ensure all values are dictionaries before using it directly.
        if raw_routes and all(isinstance(v, dict) for v in raw_routes.values()):
            return {k: v for k, v in raw_routes.items() if isinstance(v, dict)} or None

        return None
