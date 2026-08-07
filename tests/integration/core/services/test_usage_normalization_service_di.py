"""Integration tests for UsageNormalizationService DI registration.

This module tests that UsageNormalizationService can be resolved from the DI container.
"""

from __future__ import annotations

import pytest
from src.core.app.stages.core_services import CoreServicesStage
from src.core.app.stages.infrastructure import InfrastructureStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.usage_normalization_service_interface import (
    IUsageNormalizationService,
)
from src.core.services.usage_calculation_service import UsageCalculationService
from src.core.services.usage_normalization_service import UsageNormalizationService


@pytest.mark.asyncio
async def test_usage_normalization_service_resolvable_from_di() -> None:
    """Test that UsageNormalizationService can be resolved from DI container."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve UsageNormalizationService via interface
    normalization_service = provider.get_required_service(IUsageNormalizationService)
    assert normalization_service is not None
    assert isinstance(normalization_service, UsageNormalizationService)

    # Resolve UsageNormalizationService via concrete type
    normalization_service_concrete = provider.get_required_service(
        UsageNormalizationService
    )
    assert normalization_service_concrete is not None
    assert (
        normalization_service_concrete is normalization_service
    )  # Should be same instance (singleton)

    # Resolve UsageCalculationService (dependency)
    calc_service = provider.get_required_service(UsageCalculationService)
    assert calc_service is not None
    assert isinstance(calc_service, UsageCalculationService)

    # Verify the normalization service has the calculation service injected
    assert normalization_service._calculation_service is calc_service


@pytest.mark.asyncio
async def test_usage_normalization_service_singleton() -> None:
    """Test that UsageNormalizationService is registered as singleton."""
    # Setup DI container
    services = ServiceCollection()
    config = AppConfig()

    # Initialize required stages
    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    # Build service provider
    provider = services.build_service_provider()

    # Resolve multiple times
    service1 = provider.get_required_service(IUsageNormalizationService)
    service2 = provider.get_required_service(IUsageNormalizationService)
    service3 = provider.get_required_service(UsageNormalizationService)

    # All should be the same instance
    assert service1 is service2
    assert service2 is service3
