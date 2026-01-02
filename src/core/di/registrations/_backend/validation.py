"""
Backend validation services registration helpers.

Handles registration of:
- Backend Validation Service
- Validation HTTP Client Manager
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_validation_services(services: ServiceCollection) -> None:
    """Register backend validation services as singletons.

    Registers:
    - ValidationHttpClientManager as a singleton
    - IHttpClientManager mapped to ValidationHttpClientManager singleton
    - BackendValidationService as a singleton (with dependencies)
    - IBackendValidator mapped to BackendValidationService singleton

    Args:
        services: The service collection to register into
    """
    from src.core.interfaces.backend_factory_interface import IBackendFactory
    from src.core.interfaces.backend_validator_interface import IBackendValidator
    from src.core.interfaces.http_client_manager_interface import IHttpClientManager
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.backend_validation_service import BackendValidationService
    from src.core.services.validation_http_client_manager import (
        ValidationHttpClientManager,
    )

    # Register ValidationHttpClientManager as singleton
    register_singleton_if_absent(services, ValidationHttpClientManager)

    # Register IHttpClientManager interface mapped to ValidationHttpClientManager singleton
    def _http_client_manager_factory(
        provider: IServiceProvider,
    ) -> ValidationHttpClientManager:
        return provider.get_required_service(ValidationHttpClientManager)

    register_singleton_if_absent(
        services,
        cast(type, IHttpClientManager),
        implementation_factory=_http_client_manager_factory,
    )

    # Register BackendValidationService as singleton with dependencies
    def _backend_validation_service_factory(
        provider: IServiceProvider,
    ) -> BackendValidationService:
        from src.core.services.backend_factory import BackendFactory

        # Try to resolve IBackendFactory first, fallback to BackendFactory if not registered
        try:
            backend_factory: IBackendFactory = cast(
                IBackendFactory,
                provider.get_required_service(cast(type, IBackendFactory)),
            )
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            # IBackendFactory not registered, use BackendFactory directly
            backend_factory = cast(
                IBackendFactory, provider.get_required_service(BackendFactory)
            )

        backend_registry: BackendRegistry = provider.get_required_service(BackendRegistry)
        http_client_manager: IHttpClientManager = cast(
            IHttpClientManager,
            provider.get_required_service(cast(type, IHttpClientManager)),
        )

        return BackendValidationService(
            backend_factory=backend_factory,
            http_client_manager=http_client_manager,
            backend_registry=backend_registry,
        )

    register_singleton_if_absent(
        services,
        BackendValidationService,
        implementation_factory=_backend_validation_service_factory,
    )

    # Register IBackendValidator interface mapped to BackendValidationService singleton
    def _backend_validator_factory(
        provider: IServiceProvider,
    ) -> BackendValidationService:
        return provider.get_required_service(BackendValidationService)

    register_singleton_if_absent(
        services,
        cast(type, IBackendValidator),
        implementation_factory=_backend_validator_factory,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered backend validation services")
