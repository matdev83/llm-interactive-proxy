"""
Backend routing and discovery registration helpers.

Handles registration of:
- Backend Routing Service
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_routing_service(services: ServiceCollection) -> None:
    """Register BackendRoutingService for discovery/routing decisions."""
    try:
        from src.core.services.backend_routing_service import BackendRoutingService

        def _routing_service_factory(
            provider: IServiceProvider,
        ) -> BackendRoutingService:
            from src.core.config.models import RoutingConfig
            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )

            config = provider.get_required_service(AppConfig)
            routing_cfg: RoutingConfig | None = getattr(config, "routing", None)
            backend_cfg_provider: IBackendConfigProvider = (
                provider.get_required_service(cast(type, IBackendConfigProvider))
            )
            return BackendRoutingService(
                config_provider=backend_cfg_provider,
                routing_config=routing_cfg,
            )

        register_singleton_if_absent(
            services,
            BackendRoutingService,
            implementation_factory=_routing_service_factory,
        )
    except (ImportError, AttributeError, TypeError, RuntimeError):
        # Specific exceptions during service registration:
        # - ImportError: Module not found or import errors
        # - AttributeError: Missing attributes during config/provider resolution
        # - TypeError: Incorrect types during registration
        # - RuntimeError: Runtime errors during factory execution
        logger.exception("Failed to register BackendRoutingService")
        raise
