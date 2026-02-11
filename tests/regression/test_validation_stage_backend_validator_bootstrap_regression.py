"""Regression test for validation-time DI bootstrap in ApplicationBuilder.

This guards against a startup regression where stage validation could fail with
"no working backends" because IBackendValidator was missing when the builder
started from an empty service collection.
"""

from __future__ import annotations

from typing import cast

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.provider_lifecycle import (
    get_current_service_provider,
    set_service_provider,
)
from src.core.interfaces.backend_validator_interface import IBackendValidator
from src.core.interfaces.configuration_interface import IConfig


class BackendValidatorResolutionStage(InitializationStage):
    """Stage used to validate backend validator availability during validation."""

    @property
    def name(self) -> str:
        return "backend-validator-resolution"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Resolve IBackendValidator during validation"

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        provider = get_current_service_provider()
        validator: IBackendValidator = provider.get_required_service(
            cast(type, IBackendValidator)
        )
        assert validator is not None
        return True

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        return None


@pytest.mark.asyncio
async def test_validation_bootstrap_resolves_backend_validator_without_mutating_builder_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation should bootstrap baseline DI and restore pre-validation descriptors."""
    import src.core.di.services as di_services

    # Start from an empty global DI state to exercise the regression path.
    monkeypatch.setattr(di_services, "_service_collection", None, raising=False)
    set_service_provider(None)

    builder = ApplicationBuilder()
    builder.add_stage(BackendValidatorResolutionStage())

    config = AppConfig()
    builder._services.add_instance(AppConfig, config)
    builder._services.add_instance(cast(type, IConfig), config)

    descriptors_before = dict(builder._services._descriptors)

    try:
        await builder.validate_stages(config)
    finally:
        set_service_provider(None)

    descriptors_after = dict(builder._services._descriptors)
    assert descriptors_after == descriptors_before
