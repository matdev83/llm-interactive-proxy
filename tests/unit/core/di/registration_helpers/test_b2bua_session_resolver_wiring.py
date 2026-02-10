from __future__ import annotations

from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import core
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.b2bua_session_resolver_service import B2BUASessionResolver
from src.core.services.session_resolver_service import DefaultSessionResolver


def test_core_registration_uses_b2bua_resolver_when_feature_enabled() -> None:
    services = ServiceCollection()
    config = AppConfig({"session": {"b2bua": {"enabled": True}}})

    core.register(services, config)
    provider = services.build_service_provider()

    resolver: ISessionResolver = provider.get_required_service(
        cast(type, ISessionResolver)
    )
    assert isinstance(resolver, B2BUASessionResolver)


def test_core_registration_uses_legacy_resolver_when_feature_disabled() -> None:
    services = ServiceCollection()
    config = AppConfig({"session": {"b2bua": {"enabled": False}}})

    core.register(services, config)
    provider = services.build_service_provider()

    resolver: ISessionResolver = provider.get_required_service(
        cast(type, ISessionResolver)
    )
    assert isinstance(resolver, DefaultSessionResolver)
