from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from src.core.app import controllers as root_controllers
from src.core.app.controllers.models_controller import (
    get_backend_routing_service,
    get_backend_service,
)
from src.core.app.test_builder import build_test_app
from src.core.services.backend_reactivation_control import BackendReactivationControl
from src.core.services.model_capability_index import ModelCapabilitySnapshot
from src.core.services.resilience.rate_limit_state import RateLimitStateManager


class _RoutingServiceStub:
    def __init__(self) -> None:
        self._snapshot = ModelCapabilitySnapshot(
            generation=10,
            model_to_instances={
                "openai/gpt-4o": ("openai.1", "openai.2"),
                "anthropic/claude-3-5-sonnet": ("anthropic.1",),
            },
            instance_to_models={
                "openai.1": ("openai/gpt-4o",),
                "openai.2": ("openai/gpt-4o",),
                "anthropic.1": ("anthropic/claude-3-5-sonnet",),
            },
            alias_to_canonical={
                "gpt-4o": "openai/gpt-4o",
                "openai/gpt-4o": "openai/gpt-4o",
                "claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
                "anthropic/claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
            },
            created_at_monotonic=1.0,
        )

    def get_model_capability_snapshot(self) -> ModelCapabilitySnapshot:
        return self._snapshot

    def build_model_eligibility_diagnostics(
        self, *, model_limit: int, instances_per_model_limit: int
    ) -> dict[str, object]:
        return {
            "default_preference_policy": "cost",
            "proxy_selection_scope": "proxy_instance_model_selection",
            "connector_scheduling_scope": "connector_internal_and_opaque",
            "truncation": {
                "model_limit": model_limit,
                "instances_per_model_limit": instances_per_model_limit,
                "models_truncated": True,
                "models_omitted": 1,
            },
            "model_eligibility": [
                {
                    "model": "openai/gpt-4o",
                    "eligible_instances": ["openai.1", "openai.2"],
                    "eligible_instance_count": 2,
                    "instances_truncated": False,
                    "instances_omitted": 0,
                    "applied_preference_policy": "cost",
                    "equivalent_score_tie_sets": [["openai.1", "openai.2"]],
                }
            ],
        }


class _EmptyRoutingServiceStub:
    def get_model_capability_snapshot(self) -> ModelCapabilitySnapshot:
        return ModelCapabilitySnapshot(
            generation=11,
            model_to_instances={},
            instance_to_models={},
            alias_to_canonical={},
            created_at_monotonic=2.0,
        )


class _ServiceProviderStub:
    def __init__(self, routing_service: _RoutingServiceStub | None) -> None:
        self._routing_service = routing_service

    def get_service(self, service_type):  # type: ignore[no-untyped-def]
        name = getattr(service_type, "__name__", "")
        if name == "BackendRoutingService":
            return self._routing_service
        return None

    def get_required_service(self, service_type):  # type: ignore[no-untyped-def]
        service = self.get_service(service_type)
        if service is None:
            raise KeyError(f"Service not registered: {service_type}")
        return service

    def create_scope(self):  # type: ignore[no-untyped-def]
        return self

    def dispose(self) -> None:
        return None


class _LifecycleManagerStub:
    def __init__(self, *, disabled_reason: str = "auth failed") -> None:
        self._disabled = {
            "openai.1": SimpleNamespace(reason=disabled_reason, timestamp=100.0)
        }

    def get_disabled_backends(self) -> dict[str, object]:
        return dict(self._disabled)

    def reactivate(self, backend_type: str) -> bool:
        if backend_type in self._disabled:
            self._disabled.pop(backend_type, None)
            return True
        return False


def _build_backend_service_stub() -> MagicMock:
    backend = MagicMock()
    backend.get_available_models.return_value = ["openai/gpt-4o"]
    backend.is_rate_limited.return_value = False
    backend.get_retry_after_remaining.return_value = None
    backend.is_backend_functional.return_value = True
    backend.get_validation_errors.return_value = []

    service = MagicMock()
    service.get_active_backends.return_value = {"openai.1": backend}
    return service


def test_anthropic_models_uses_canonical_ids_from_capability_snapshot(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()

    routing_stub = _RoutingServiceStub()
    backend_service_stub = _build_backend_service_stub()
    provider_stub = _ServiceProviderStub(routing_stub)

    async def _get_backend_service_stub():
        return backend_service_stub

    monkeypatch.setattr(
        root_controllers, "get_backend_service", _get_backend_service_stub
    )
    app.dependency_overrides[root_controllers.get_service_provider_dependency] = (
        lambda: provider_stub
    )

    with TestClient(app) as client:
        response = client.get("/anthropic/v1/models")
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["data"]]
        assert "anthropic/claude-3-5-sonnet" in ids
        assert "anthropic:claude-3-5-sonnet" not in ids


def test_v1_models_is_canonical_even_with_legacy_query_flag(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()

    routing_stub = _RoutingServiceStub()
    backend_service_stub = _build_backend_service_stub()

    app.dependency_overrides[get_backend_service] = lambda: backend_service_stub
    app.dependency_overrides[get_backend_routing_service] = lambda: routing_stub

    with TestClient(app) as client:
        canonical_response = client.get("/v1/models")
        assert canonical_response.status_code == 200
        canonical_ids = [item["id"] for item in canonical_response.json()["data"]]
        assert "openai/gpt-4o" in canonical_ids
        assert "openai:gpt-4o" not in canonical_ids

        legacy_query_response = client.get("/v1/models?include_legacy_ids=true")
        assert legacy_query_response.status_code == 200
        legacy_query_ids = [item["id"] for item in legacy_query_response.json()["data"]]
        assert "openai/gpt-4o" in legacy_query_ids
        assert "openai:gpt-4o" not in legacy_query_ids


def test_v1_models_returns_empty_when_capability_snapshot_empty(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()

    routing_stub = _EmptyRoutingServiceStub()
    backend_service_stub = _build_backend_service_stub()

    app.dependency_overrides[get_backend_service] = lambda: backend_service_stub
    app.dependency_overrides[get_backend_routing_service] = lambda: routing_stub

    with TestClient(app) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_v1_diagnostics_includes_routing_metadata_and_boundedness(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.setenv("LLM_PROXY_DIAGNOSTICS_MODEL_LIMIT", "2")
    monkeypatch.setenv("LLM_PROXY_DIAGNOSTICS_INSTANCES_PER_MODEL_LIMIT", "1")
    app = build_test_app()

    routing_stub = _RoutingServiceStub()
    backend_service_stub = _build_backend_service_stub()

    lifecycle_stub = MagicMock()
    lifecycle_stub.get_disabled_backends.return_value = {}

    state_manager = MagicMock()
    state_manager.get_all_instance_states.return_value = {
        "openai.1": {
            "status": "rate_limited",
            "cooldown_remaining": 5.0,
            "disabled_reason": None,
            "disabled_at": None,
        }
    }
    resilience_stub = MagicMock()
    resilience_stub.state_manager = state_manager

    from src.core.app.controllers import diagnostics_controller

    monkeypatch.setattr(
        diagnostics_controller,
        "_get_backend_routing_service_if_available",
        lambda: routing_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_backend_lifecycle_manager_if_available",
        lambda: lifecycle_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_resilience_coordinator_if_available",
        lambda: resilience_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_activity_tracker_if_enabled",
        lambda: None,
    )

    app.dependency_overrides[diagnostics_controller.verify_local_access] = lambda: None
    app.dependency_overrides[get_backend_service] = lambda: backend_service_stub

    with TestClient(app) as client:
        response = client.get("/v1/diagnostics")
        assert response.status_code == 200
        payload = response.json()

        assert payload["routing"]["default_preference_policy"] == "cost"
        assert payload["routing"]["truncation"]["model_limit"] == 2
        assert payload["routing"]["truncation"]["instances_per_model_limit"] == 1
        assert payload["routing"]["truncation"]["models_truncated"] is True
        assert payload["routing"]["model_eligibility"][0][
            "equivalent_score_tie_sets"
        ] == [["openai.1", "openai.2"]]

        first_instance = payload["instances"][0]
        assert first_instance["name"] == "openai.1"
        assert first_instance["availability_status"] == "rate_limited"
        assert first_instance["cooldown_remaining_seconds"] == 5.0


def test_v1_diagnostics_reactivation_endpoint_updates_state(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()

    routing_stub = _RoutingServiceStub()
    backend_service_stub = _build_backend_service_stub()
    lifecycle_stub = _LifecycleManagerStub(disabled_reason="auth failed")

    state_manager = RateLimitStateManager()
    state_manager.disable_instance("openai.1", "auth failed")
    state_manager.mark_model_unsupported(
        "openai.1",
        "openai/gpt-4o",
        "provider rejected model",
    )
    resilience_stub = SimpleNamespace(state_manager=state_manager)

    control = BackendReactivationControl(
        backend_lifecycle_manager=cast(Any, lifecycle_stub),
        resilience_coordinator=cast(Any, resilience_stub),
    )

    from src.core.app.controllers import diagnostics_controller

    monkeypatch.setattr(
        diagnostics_controller,
        "_get_backend_routing_service_if_available",
        lambda: routing_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_backend_lifecycle_manager_if_available",
        lambda: lifecycle_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_resilience_coordinator_if_available",
        lambda: resilience_stub,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_backend_reactivation_control_if_available",
        lambda: control,
    )
    monkeypatch.setattr(
        diagnostics_controller,
        "_get_activity_tracker_if_enabled",
        lambda: None,
    )

    app.dependency_overrides[diagnostics_controller.verify_local_access] = lambda: None
    app.dependency_overrides[get_backend_service] = lambda: backend_service_stub

    with TestClient(app) as client:
        before = client.get("/v1/diagnostics")
        assert before.status_code == 200
        assert before.json()["instances"][0]["availability_status"] == "disabled"

        reactivate_response = client.post(
            "/v1/diagnostics/backends/openai.1/reactivate", json={}
        )
        assert reactivate_response.status_code == 200
        payload = reactivate_response.json()
        assert payload["reactivated"] is True
        assert payload["unsupported_pairs_cleared"] == 0

        mid_model_state = state_manager.get_all_model_states()
        assert (
            mid_model_state["openai.1:openai/gpt-4o"]["unsupported_permanent"] is True
        )

        after = client.get("/v1/diagnostics")
        assert after.status_code == 200
        assert after.json()["instances"][0]["availability_status"] == "active"

        clear_response = client.post(
            "/v1/diagnostics/backends/openai.1/reactivate",
            json={"clear_unsupported": True},
        )
        assert clear_response.status_code == 200
        assert clear_response.json()["unsupported_pairs_cleared"] == 1
        assert "openai.1:openai/gpt-4o" not in state_manager.get_all_model_states()
