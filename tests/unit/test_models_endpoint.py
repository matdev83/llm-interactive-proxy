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
        lambda: ["gemini-oauth-plan"],
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

    from unittest.mock import Mock

    result = asyncio.run(
        _list_models_impl(
            backend_service=Mock(),
            config=config,
            backend_factory=DummyFactory(),  # type: ignore
        )
    )

    model_ids = {model["id"] for model in result["data"]}
    assert "gemini-oauth-plan:gemini-2.5-pro" in model_ids
    assert created_backends == ["gemini-oauth-plan"]


def test_model_listing_respects_injected_config(monkeypatch) -> None:
    """Ensure the controller honours custom configurations supplied via DI."""

    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.core.app.controllers import models_controller
    from src.core.app.controllers.models_controller import _list_models_impl

    monkeypatch.setattr(
        models_controller.backend_registry,
        "get_registered_backends",
        lambda: ["dummy"],
    )

    class DummyBackend:
        def get_available_models(self) -> list[str]:
            return ["dummy-model"]

    class DummyFactory:
        def __init__(self) -> None:
            self.created_with: list[tuple[str, object]] = []

        def create_backend(self, backend_type: str, config_obj: object) -> DummyBackend:
            self.created_with.append((backend_type, config_obj))
            return DummyBackend()

    class CustomBackends:
        def __init__(self) -> None:
            self.functional_backends = {"dummy"}
            self.dummy = SimpleNamespace(api_key="token")

    class CustomConfig:
        def __init__(self) -> None:
            self.backends = CustomBackends()

        def get(self, key: str, default: object | None = None) -> object | None:
            if key == "backends":
                return self.backends
            return default

        def set(self, key: str, value: object) -> None:
            setattr(self, key, value)

    factory = DummyFactory()
    config = CustomConfig()

    result = asyncio.run(
        _list_models_impl(
            backend_service=Mock(),
            config=config,  # type: ignore[arg-type]
            backend_factory=factory,  # type: ignore[arg-type]
        )
    )

    model_ids = {model["id"] for model in result["data"]}
    assert "dummy:dummy-model" in model_ids
    assert factory.created_with == [("dummy", config)]
