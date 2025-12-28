"""
Resilience registrar.

Registers failover, rate limiting, failure strategy, and backend completion flow services.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._resilience_backend_flow import (
    register_backend_completion_flow_services,
)
from src.core.di.registrations._resilience_coordination import (
    register_resilience_coordination_services,
)

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register resilience services.

    This registrar handles:
    - Failure handling strategies (optional, based on config)
    - Rate limiting (registered in infrastructure stage)
    - Failover coordination (optional)
    - Backend completion flow collaborators (registered in core)

    Note: Many resilience services are registered elsewhere (e.g., RateLimiter in
    InfrastructureStage, BackendCompletionFlow in core registrar). This registrar
    focuses on failure handling strategy registration when enabled.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # CRITICAL: Preserve exact registration order
    register_resilience_coordination_services(services, app_config)
    register_backend_completion_flow_services(services)
