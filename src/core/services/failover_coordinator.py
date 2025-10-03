from __future__ import annotations

from typing import Any

from src.core.domain.model_utils import parse_model_backend
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
        attempts: list[FailoverAttempt] = []

        routes_snapshot = dict(self._svc.failover_routes)

        # First handle simple backend -> backend mappings maintained by
        # FailoverService (e.g. {"openai": "anthropic"}).
        if backend_type in routes_snapshot:
            direct_route = routes_snapshot[backend_type]

            if isinstance(direct_route, str):
                attempts.append(FailoverAttempt(backend=direct_route, model=model))
            elif isinstance(direct_route, list):
                attempts.extend(
                    self._parse_elements(direct_route, backend_type, model)
                )
            elif isinstance(direct_route, dict):
                backend_override = direct_route.get("backend")
                model_override = direct_route.get("model")

                if isinstance(backend_override, str) and isinstance(model_override, str):
                    attempts.append(
                        FailoverAttempt(backend=backend_override, model=model_override)
                    )
                else:
                    elements = direct_route.get("elements")
                    if isinstance(elements, list):
                        attempts.extend(
                            self._parse_elements(elements, backend_type, model)
                        )

        # Advanced failover routes are keyed by model name (complex per-model
        # policies). Delegate to FailoverService for that shape.
        if not attempts and model in routes_snapshot:
            class _Adapter:
                def __init__(self, routes: dict[str, Any]):
                    self.failover_routes: dict[str, dict[str, Any]] = routes

            adapter = _Adapter(routes_snapshot)
            attempts = self._svc.get_failover_attempts(adapter, model, backend_type)

        return attempts

    def _parse_elements(
        self, elements: list[Any], backend_type: str, fallback_model: str
    ) -> list[FailoverAttempt]:
        parsed: list[FailoverAttempt] = []
        for element in elements:
            backend, parsed_model = parse_model_backend(
                str(element), default_backend=backend_type
            )
            parsed.append(
                FailoverAttempt(
                    backend=backend or backend_type,
                    model=parsed_model or fallback_model,
                )
            )
        return parsed

    def register_route(self, model: str, route: dict) -> None:
        # Route registration is handled on the underlying service.
        self._svc.failover_routes[model] = route
