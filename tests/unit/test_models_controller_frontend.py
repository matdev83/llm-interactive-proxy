import asyncio
import types
from typing import Any

from src.core.app.controllers.models_controller import _list_models_impl
from src.core.services.backend_registry import backend_registry


class DummyBackend:
    async def get_available_models(self) -> list[str]:
        return ["test-model"]


class DummyBackendFactory:
    def __init__(self, expected_config: Any) -> None:
        self.expected_config = expected_config

    def create_backend(self, backend_type: str, config: Any) -> DummyBackend:
        assert backend_type == "test-backend"
        # Ensure the controller passes through the injected config rather than replacing it
        assert config is self.expected_config
        return DummyBackend()


class DummyBackendSettings:
    def __init__(self) -> None:
        backend_config = types.SimpleNamespace(api_key="abc123", identity=None, extra=None)
        self.functional_backends = {"test-backend"}
        setattr(self, "test-backend", backend_config)


class DummyConfig:
    def __init__(self) -> None:
        self.backends = DummyBackendSettings()


def test_models_controller_preserves_injected_config(monkeypatch) -> None:
    dummy_config = DummyConfig()
    backend_factory = DummyBackendFactory(expected_config=dummy_config)

    # Patch the backend registry to expose only our test backend
    monkeypatch.setattr(
        backend_registry, "get_registered_backends", lambda: ["test-backend"], raising=False
    )

    result = asyncio.run(
        _list_models_impl(
            backend_service=object(),
            config=dummy_config,
            backend_factory=backend_factory,
        )
    )

    assert any(model["id"] == "test-backend:test-model" for model in result["data"])
