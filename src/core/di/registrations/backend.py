"""
Backend registrar.

Registers backend registry, factory, routing, and translation services.
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._backend.core_services import (
    register_backend_registry,
    register_translation_service,
)
from src.core.di.registrations._backend.extracted_services import (
    register_extracted_backend_services,
)
from src.core.di.registrations._backend.factory import (
    register_backend_config_provider,
    register_backend_factory,
)
from src.core.di.registrations._backend.infrastructure import (
    register_http_client,
    register_rate_limiter,
    register_wire_capture,
)
from src.core.di.registrations._backend.lifestyle import (
    register_backend_lifecycle_manager,
    register_backend_model_resolver,
)
from src.core.di.registrations._backend.main_service import register_backend_service
from src.core.di.registrations._backend.routing import register_backend_routing_service

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register backend services.

    This registrar handles:
    - Backend registry
    - Backend factory
    - Backend service
    - Translation service
    - Routing services
    - Backend configuration provider

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    register_http_client(services)
    register_rate_limiter(services)
    register_wire_capture(services)
    register_backend_registry(services)
    register_translation_service(services)
    register_backend_factory(services, app_config)
    register_backend_config_provider(services)
    register_backend_routing_service(services)
    register_extracted_backend_services(services)
    register_backend_lifecycle_manager(services)
    register_backend_model_resolver(services)
    register_backend_service(services)
