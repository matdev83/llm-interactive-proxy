from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app


def test_models_endpoint_lists_all(monkeypatch) -> None:
    # No backend mocking required: controller uses a default model list if none discovered
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/models")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0


def test_v1_models_endpoint_lists_all(monkeypatch) -> None:
    # No backend mocking required: controller uses a default model list if none discovered
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) > 0


import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


def test_model_listing_includes_oauth_backends(monkeypatch) -> None:
    import asyncio

    from src.core.app.controllers import models_controller
    from src.core.app.controllers.models_controller import _list_models_impl
    from src.core.config.app_config import AppConfig

    monkeypatch.setattr(
        models_controller.backend_registry,
        "get_registered_backends",
        lambda: ["gemini-cli-oauth-personal"],
    )

    config = AppConfig()

    created_backends: list[str] = []

    class DummyBackend:
        async def get_available_models(self) -> list[str]:
            return ["gemini-2.5-pro"]

    class DummyFactory:
        def create_backend(
            self, backend_type: str, config_obj: AppConfig
        ) -> DummyBackend:
            created_backends.append(backend_type)
            return DummyBackend()

    result = asyncio.run(
        _list_models_impl(
            backend_service=object(),
            config=config,
            backend_factory=DummyFactory(),
        )
    )

    model_ids = {model["id"] for model in result["data"]}
    assert "gemini-cli-oauth-personal:gemini-2.5-pro" in model_ids
    assert created_backends == ["gemini-cli-oauth-personal"]
