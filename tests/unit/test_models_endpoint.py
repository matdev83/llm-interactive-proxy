from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from src.core.app.controllers.models_controller import _list_models_impl
from src.core.app.test_builder import build_test_app
from src.core.services.model_capability_index import ModelCapabilitySnapshot

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


def test_models_endpoint_returns_openai_list_shape(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/models")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["object"] == "list"
        assert isinstance(payload["data"], list)


def test_v1_models_endpoint_returns_openai_list_shape(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["object"] == "list"
        assert isinstance(payload["data"], list)


def test_list_models_impl_uses_capability_snapshot_for_oauth_backends() -> None:
    class RoutingServiceStub:
        def get_model_capability_snapshot(self) -> ModelCapabilitySnapshot:
            return ModelCapabilitySnapshot(
                generation=7,
                model_to_instances={"gemini-2.5-pro": ("gemini-oauth-plan.1",)},
                instance_to_models={"gemini-oauth-plan.1": ("gemini-2.5-pro",)},
                alias_to_canonical={
                    "gemini-2.5-pro": "gemini-2.5-pro",
                },
                created_at_monotonic=1.0,
            )

    backend_service = Mock()
    backend_service.get_active_backends.return_value = {}

    result, _ = asyncio.run(
        _list_models_impl(
            backend_service=backend_service,
            routing_service=RoutingServiceStub(),
        )
    )

    model_ids = {model.id for model in result.data}
    assert "gemini-oauth-plan/gemini-2.5-pro" in model_ids
