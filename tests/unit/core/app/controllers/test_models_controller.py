from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from src.core.app.controllers.models_controller import get_backend_factory_service
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


@pytest.mark.asyncio
async def test_backend_factory_fallback_uses_di_translation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the fallback path reuses DI-managed services instead of new instances."""

    translation_service = TranslationService()
    sentinel = object()
    translation_service.register_converter("response", "sentinel", lambda *_: sentinel)

    http_client = Mock(spec=httpx.AsyncClient)
    config = AppConfig()

    provider = _DummyProvider(
        {
            httpx.AsyncClient: http_client,
            BackendRegistry: backend_registry,
            AppConfig: config,
            TranslationService: translation_service,
        }
    )

    monkeypatch.setattr(
        "src.core.di.services.get_or_build_service_provider",
        lambda: provider,
    )

    factory = get_backend_factory_service()

    assert isinstance(factory, BackendFactory)
    assert factory._translation_service is translation_service
    assert factory._client is http_client
    converter = factory._translation_service._to_domain_response_converters["sentinel"]
    assert converter(None) is sentinel


def test_get_config_service_handles_service_resolution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.core.app.controllers import models_controller

    class FailingProvider:
        def get_required_service(self, service_type: Any) -> Any:
            raise ServiceResolutionError(
                "No service registered", service_name=str(service_type)
            )

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: FailingProvider(),
    )

    fake_context = SimpleNamespace(
        _request_context=SimpleNamespace(exists=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "starlette.context", fake_context)

    config = models_controller.get_config_service()

    assert isinstance(config, AppConfig)
