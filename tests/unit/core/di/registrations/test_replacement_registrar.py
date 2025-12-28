"""
Tests for model replacement services registrar.

These tests verify that:
- Model replacement services register when enabled
- Registration is skipped when disabled
- Orchestrator wiring includes the replacement registrar
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import replacement
from src.core.di.registrations._backend.core_services import register_backend_registry
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService

if TYPE_CHECKING:
    from src.connectors.base import LLMBackend


def _build_enabled_config() -> AppConfig:
    replacement_config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="test-backend:test-model",
        turn_count=1,
    )
    return AppConfig().model_copy(update={"replacement": replacement_config})


def _register_test_backend(registry: BackendRegistry) -> None:
    def _factory() -> LLMBackend:
        raise RuntimeError("Test backend factory should not be invoked")

    registry.register_backend("test-backend", _factory)


def test_replacement_service_skipped_when_disabled() -> None:
    services = ServiceCollection()
    config = AppConfig()

    replacement.register(services, config)
    provider = services.build_service_provider()

    service = provider.get_service(cast(type, IModelReplacementService))
    assert service is None


def test_replacement_service_registered_when_enabled() -> None:
    services = ServiceCollection()
    config = _build_enabled_config()

    register_singleton_if_absent(services, AppConfig, instance=config)
    register_backend_registry(services)
    replacement.register(services, config)
    provider = services.build_service_provider()

    registry = provider.get_required_service(BackendRegistry)
    _register_test_backend(registry)

    service = provider.get_service(ModelReplacementService)
    assert isinstance(service, ModelReplacementService)

    interface_service = provider.get_service(cast(type, IModelReplacementService))
    assert isinstance(interface_service, ModelReplacementService)


def test_replacement_registrar_runs_in_orchestrator() -> None:
    from src.core.di.registrations._orchestrator import register_all

    services = ServiceCollection()
    config = _build_enabled_config()

    register_all(services, config)
    provider = services.build_service_provider()

    registry = provider.get_required_service(BackendRegistry)
    _register_test_backend(registry)

    service = provider.get_service(cast(type, IModelReplacementService))
    assert isinstance(service, ModelReplacementService)
