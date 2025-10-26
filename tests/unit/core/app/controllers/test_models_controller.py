from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from src.core.app.controllers.models_controller import (
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
    get_backend_factory_service,
)
from src.core.common.exceptions import ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry, backend_registry
from src.core.services.translation_service import TranslationService


class _DummyProvider:
    """Minimal service provider for exercising fallback construction."""

    def __init__(self, services: dict[Any, Any]) -> None:
        self._services = services

    def get_required_service(
        self, service_type: Any
    ) -> Any:  # pragma: no cover - thin wrapper
        if service_type is BackendFactory:
            raise KeyError("BackendFactory not registered")
        try:
            return self._services[service_type]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(service_type) from exc

    def set_service(self, service_type: type, service: Any) -> None:
        self._services[service_type] = service


@pytest.mark.asyncio
async def test_backend_factory_fallback_uses_di_translation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the fallback path reuses DI-managed services instead of new instances."""

    translation_service = TranslationService()
    sentinel = object()
    translation_service.register_converter("response", "sentinel", lambda *_: sentinel)

    http_client = MagicMock()
    base_config = AppConfig()
    openai_config = base_config.backends.openai.model_copy(
        update={"api_key": ("test",)}
    )
    backends_config = base_config.backends.model_copy(update={"openai": openai_config})
    config = base_config.model_copy(update={"backends": backends_config})

    provider = _DummyProvider(
        {
            httpx.AsyncClient: http_client,
            BackendRegistry: backend_registry,
            AppConfig: config,
            TranslationService: translation_service,
        }
    )

    def fake_service_collection():
        from src.core.di.container import ServiceCollection

        services = ServiceCollection()
        services.add_instance(BackendRegistry, backend_registry)
        services.add_instance(AppConfig, config)
        services.add_instance(httpx.AsyncClient, http_client)
        services.add_instance(TranslationService, translation_service)
        services.add_singleton(
            BackendFactory,
            implementation_factory=lambda provider: BackendFactory(
                http_client, backend_registry, config, translation_service
            ),
        )
        return services

    monkeypatch.setattr(
        "src.core.di.services.get_or_build_service_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        "src.core.di.services.get_service_collection",
        fake_service_collection,
    )

    factory = get_backend_factory_service()

    assert isinstance(factory, BackendFactory)
    assert factory._translation_service is translation_service
    assert factory._client is http_client


def test_get_config_service_handles_service_resolution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.app.controllers import models_controller

    class FailingProvider:
        def get_required_service(self, service_type: Any) -> Any:
            raise ServiceResolutionError(
                "No service registered", service_name=str(service_type)
            )

    failing_provider = FailingProvider()
    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: failing_provider,
    )

    context_stub = SimpleNamespace(
        _request_context=SimpleNamespace(exists=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "starlette.context", context_stub)

    config = models_controller.get_config_service()

    assert isinstance(config, AppConfig)

    original_resolver = models_controller._resolve_backend_factory_from_provider

    def failing_resolver(_provider: Any) -> BackendFactory:
        raise ServiceResolutionError("missing", "BackendFactory")

    monkeypatch.setattr(
        "src.core.app.controllers.models_controller._resolve_backend_factory_from_provider",
        failing_resolver,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_backend_factory_service()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == HTTP_503_SERVICE_UNAVAILABLE_MESSAGE

    monkeypatch.setattr(
        "src.core.app.controllers.models_controller._resolve_backend_factory_from_provider",
        original_resolver,
    )
