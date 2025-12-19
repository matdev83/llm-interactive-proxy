"""
Registrar orchestrator.

Provides a single entry point that calls all feature-scoped registrars in
deterministic order, aligned with staged initialization requirements.
"""

from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

# Import registrars in deterministic order (as specified in design.md)
from src.core.di.registrations import (
    backend,
    core,
    persistence,
    resilience,
    security,
    streaming,
    tooling,
)


def register_all(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register all feature-scoped services in deterministic order.

    The order is:
    1. core - Config, session, app state primitives
    2. streaming - Streaming pipeline
    3. persistence - Database, repositories, memory
    4. security - Sandboxing, path validation
    5. tooling - Tool call reactor, dangerous commands
    6. backend - Backend registry, factory, routing
    7. resilience - Failover, rate limiting, failure strategy

    This order is critical to preserve staged initialization semantics and
    ensure dependencies are registered before dependents.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register in deterministic order (as specified in design.md)
    core.register(services, app_config)
    streaming.register(services, app_config)
    persistence.register(services, app_config)
    security.register(services, app_config)
    tooling.register(services, app_config)
    backend.register(services, app_config)
    resilience.register(services, app_config)
