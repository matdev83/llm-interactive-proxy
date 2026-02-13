"""Integration tests for usage tracking infrastructure.

This module tests that the usage tracking services are properly registered
and can be used through the DI container.
"""

import pytest
from src.core.config.app_config import AppConfig
from src.core.interfaces.statistics_service_interface import IStatisticsService
from src.core.interfaces.usage_recording_interface import IUsageRecordingService
from src.core.services.in_memory_usage_store import InMemoryUsageStore


@pytest.mark.asyncio
async def test_usage_tracking_services_registered():
    """Test that usage tracking services are registered in DI container."""
    from src.core.app.test_builder import build_test_app_async

    config = AppConfig.from_env()
    app = await build_test_app_async(config)

    # Verify services are registered
    service_provider = app.state.service_provider

    # Check InMemoryUsageStore
    store = service_provider.get_service(InMemoryUsageStore)
    assert store is not None, "InMemoryUsageStore should be registered"

    # Check IUsageRecordingService
    usage_service = service_provider.get_service(IUsageRecordingService)
    assert usage_service is not None, "IUsageRecordingService should be registered"

    # Check IStatisticsService
    stats_service = service_provider.get_service(IStatisticsService)
    assert stats_service is not None, "IStatisticsService should be registered"


@pytest.mark.asyncio
async def test_usage_tracking_disabled():
    """Test that usage tracking services are not registered when disabled."""
    from src.core.app.test_builder import build_test_app_async
    from src.core.config.app_config import UsageTrackingConfig

    config = AppConfig.from_env()
    config = config.model_copy(
        update={"usage_tracking": UsageTrackingConfig(enabled=False)}
    )
    app = await build_test_app_async(config)

    # Verify services are not registered
    service_provider = app.state.service_provider

    # Check that services are not available
    store = service_provider.get_service(InMemoryUsageStore)
    assert store is None, "InMemoryUsageStore should not be registered when disabled"

    usage_service = service_provider.get_service(IUsageRecordingService)
    assert (
        usage_service is None
    ), "IUsageRecordingService should not be registered when disabled"

    stats_service = service_provider.get_service(IStatisticsService)
    assert (
        stats_service is None
    ), "IStatisticsService should not be registered when disabled"


@pytest.mark.asyncio
async def test_usage_tracking_config_values():
    """Test that usage tracking configuration values are properly set."""
    from src.core.app.test_builder import build_test_app_async
    from src.core.config.app_config import UsageTrackingConfig

    custom_config = UsageTrackingConfig(
        enabled=True,
        persistence_path="./custom/path.json",
        flush_interval_seconds=60.0,
        max_records_in_memory=50000,
    )
    config = AppConfig.from_env()
    config = config.model_copy(update={"usage_tracking": custom_config})
    app = await build_test_app_async(config)

    # Verify config values are accessible
    app_config = app.state.service_provider.get_required_service(AppConfig)
    assert app_config.usage_tracking.enabled is True
    assert app_config.usage_tracking.persistence_path == "./custom/path.json"
    assert app_config.usage_tracking.flush_interval_seconds == 60.0
    assert app_config.usage_tracking.max_records_in_memory == 50000
