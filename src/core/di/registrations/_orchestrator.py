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
    non_forwardable,
    persistence,
    replacement,
    resilience,
    security,
    streaming,
    tooling,
)


def register_all(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register all feature-scoped services in deterministic order.

    The order is:
    1. core - Config, session, app state primitives
    2. non_forwardable - Non-forwardable message tagging (identity, registry)
    3. streaming - Streaming pipeline
    4. persistence - Database, repositories, memory
    5. security - Sandboxing, path validation
    6. tooling - Tool call reactor, dangerous commands
    7. backend - Backend registry, factory, routing
    8. replacement - Random model replacement
    9. resilience - Failover, rate limiting, failure strategy

    This order is critical to preserve staged initialization semantics and
    ensure dependencies are registered before dependents.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register in deterministic order (as specified in design.md)
    core.register(services, app_config)
    non_forwardable.register(services, app_config)
    streaming.register(services, app_config)
    persistence.register(services, app_config)
    security.register(services, app_config)
    tooling.register(services, app_config)
    backend.register(services, app_config)
    replacement.register(services, app_config)
    resilience.register(services, app_config)
