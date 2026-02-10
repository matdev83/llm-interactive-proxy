from __future__ import annotations

from typing import cast

import pytest
from src.core.app.stages.core_services import CoreServicesStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.b2bua_session_resolver_service import B2BUASessionResolver
from src.core.services.session_resolver_service import DefaultSessionResolver


@pytest.mark.asyncio
async def test_core_services_stage_uses_b2bua_resolver_when_enabled() -> None:
    services = ServiceCollection()
    config = AppConfig({"session": {"b2bua": {"enabled": True}}})

    stage = CoreServicesStage()
    await stage.execute(services, config)

    provider = services.build_service_provider()
    resolver: ISessionResolver = provider.get_required_service(
        cast(type, ISessionResolver)
    )
    assert isinstance(resolver, B2BUASessionResolver)


@pytest.mark.asyncio
async def test_core_services_stage_uses_legacy_resolver_when_disabled() -> None:
    services = ServiceCollection()
    config = AppConfig({"session": {"b2bua": {"enabled": False}}})

    stage = CoreServicesStage()
    await stage.execute(services, config)

    provider = services.build_service_provider()
    resolver: ISessionResolver = provider.get_required_service(
        cast(type, ISessionResolver)
    )
    assert isinstance(resolver, DefaultSessionResolver)
