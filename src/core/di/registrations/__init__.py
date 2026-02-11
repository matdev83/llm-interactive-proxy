"""Feature-scoped DI registration modules."""

from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection


def register_all(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register all feature registrars in deterministic order."""
    from src.core.di.registrations._orchestrator import register_all as _register_all

    _register_all(services, app_config)


__all__ = ["register_all"]
