from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig, RoutingConfig
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.services.backend_routing_service import BackendRoutingService


def _build_provider(
    *,
    app_config: AppConfig,
    routing_service: Mock,
    backend_lifecycle_manager: Mock | None,
) -> Mock:
    provider = Mock()

    def _get_service(service_type: object) -> object | None:
        if service_type is AppConfig:
            return app_config
        if service_type is BackendRoutingService:
            return routing_service
        if service_type is IBackendLifecycleManager:  # type: ignore[type-abstract]
            return backend_lifecycle_manager
        return None

    provider.get_service.side_effect = _get_service
    return provider


@pytest.mark.asyncio
async def test_lifespan_schedules_startup_and_periodic_capability_refresh() -> None:
    builder = ApplicationBuilder()
    builder._services = Mock()
    builder._services.dispose = AsyncMock()

    routing_service = Mock()
    routing_service.refresh_model_capabilities = AsyncMock(return_value=True)
    routing_service.start_model_capability_refresh = AsyncMock(return_value=None)
    routing_service.stop_model_capability_refresh = AsyncMock(return_value=None)

    app_config = AppConfig(
        routing=RoutingConfig(capability_refresh_interval_seconds=30.0)
    )
    provider = _build_provider(
        app_config=app_config,
        routing_service=routing_service,
        backend_lifecycle_manager=None,
    )

    app = FastAPI()
    builder._add_lifecycle_handlers(app, provider)

    async with app.router.lifespan_context(app):
        # Allow fire-and-forget startup tasks to run once.
        await asyncio.sleep(0)

    routing_service.refresh_model_capabilities.assert_awaited_once_with(
        reason="startup"
    )
    routing_service.start_model_capability_refresh.assert_awaited_once()
    routing_service.stop_model_capability_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_stops_capability_refresh_before_backend_shutdown() -> None:
    builder = ApplicationBuilder()
    builder._services = Mock()
    builder._services.dispose = AsyncMock()

    call_order: list[str] = []

    async def _record_stop_refresh() -> None:
        call_order.append("stop_refresh")

    async def _record_backend_shutdown() -> None:
        call_order.append("shutdown_backends")

    routing_service = Mock()
    routing_service.refresh_model_capabilities = AsyncMock(return_value=True)
    routing_service.start_model_capability_refresh = AsyncMock(return_value=None)
    routing_service.stop_model_capability_refresh = AsyncMock(
        side_effect=_record_stop_refresh
    )

    backend_lifecycle_manager = Mock()
    backend_lifecycle_manager.shutdown_all = AsyncMock(
        side_effect=_record_backend_shutdown
    )

    app_config = AppConfig(
        routing=RoutingConfig(capability_refresh_interval_seconds=15.0)
    )
    provider = _build_provider(
        app_config=app_config,
        routing_service=routing_service,
        backend_lifecycle_manager=backend_lifecycle_manager,
    )

    app = FastAPI()
    builder._add_lifecycle_handlers(app, provider)

    with patch(
        "src.core.services.backend_startup_disablement.apply_backend_disablement_at_startup"
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    assert "stop_refresh" in call_order
    assert "shutdown_backends" in call_order
    assert call_order.index("stop_refresh") < call_order.index("shutdown_backends")
