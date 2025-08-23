"""
Backend services initialization stage.

This stage registers backend-related services:
- Backend registry
- Backend factory
- Backend configuration provider
- Backend service
"""

from __future__ import annotations

import logging
from typing import cast

import httpx

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import backend_registry

from .base import InitializationStage

logger = logging.getLogger(__name__)


class BackendStage(InitializationStage):
    """
    Stage for registering backend-related services.

    This stage registers:
    - Backend registry (singleton instance)
    - Backend factory (with HTTP client dependency)
    - Backend configuration provider
    - Backend service (main backend interface)
    """

    @property
    def name(self) -> str:
        return "backends"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register backend services (registry, factory, service)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register backend services."""
        logger.info("Initializing backend services...")

        try:
            logger.debug(
                f"Imported connectors, registered backends: {backend_registry.get_registered_backends()}"
            )
        except ImportError as e:
            logger.warning(f"Failed to import connectors: {e}")

        self._register_backend_registry(services)
        self._register_backend_factory(services)
        self._register_backend_config_provider(services)
        self._register_backend_service(services)

        logger.info("Backend services initialized successfully")

    def _register_backend_registry(self, services: ServiceCollection) -> None:
        """Register backend registry as singleton instance."""
        try:
            from src.core.services.backend_registry import (
                BackendRegistry,
                backend_registry,
            )

            services.add_instance(BackendRegistry, backend_registry)

            logger.debug("Registered backend registry instance")
        except ImportError as e:
            logger.warning(f"Could not register backend registry: {e}")

    def _register_backend_factory(self, services: ServiceCollection) -> None:
        """Register backend factory with HTTP client dependency."""
        try:
            import httpx

            from src.core.services.backend_factory import BackendFactory

            def backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
                """Factory function for creating BackendFactory with dependencies."""
                from src.core.services.backend_registry import BackendRegistry

                httpx_client: httpx.AsyncClient = provider.get_required_service(
                    httpx.AsyncClient
                )
                backend_registry_instance: BackendRegistry = (
                    provider.get_required_service(BackendRegistry)
                )
                return BackendFactory(httpx_client, backend_registry_instance)

            services.add_singleton(
                BackendFactory, implementation_factory=backend_factory_factory
            )

            logger.debug("Registered backend factory with dependencies")
        except ImportError as e:
            logger.warning(f"Could not register backend factory: {e}")

    def _register_backend_config_provider(self, services: ServiceCollection) -> None:
        """Register backend configuration provider."""
        try:
            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.services.backend_config_provider import BackendConfigProvider

            def backend_config_provider_factory(
                provider: IServiceProvider,
            ) -> BackendConfigProvider:
                """Factory function for creating BackendConfigProvider."""
                app_config = provider.get_required_service(AppConfig)
                return BackendConfigProvider(app_config)

            services.add_singleton(
                cast(type, IBackendConfigProvider),
                implementation_factory=backend_config_provider_factory,
            )

            logger.debug("Registered backend config provider")
        except ImportError as e:
            logger.warning(f"Could not register backend config provider: {e}")

    def _register_backend_service(self, services: ServiceCollection) -> None:
        """Register main backend service with all dependencies."""
        try:
            from src.core.interfaces.backend_config_provider_interface import (
                IBackendConfigProvider,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.backend_service import BackendService
            from src.core.services.rate_limiter_service import RateLimiter

            def backend_service_factory(provider: IServiceProvider) -> BackendService:
                """Factory function for creating BackendService with all dependencies."""
                from typing import cast

                from src.core.config.app_config import AppConfig
                from src.core.services.backend_factory import BackendFactory

                backend_factory: BackendFactory = provider.get_required_service(
                    BackendFactory
                )
                rate_limiter: RateLimiter = provider.get_required_service(RateLimiter)
                app_config: AppConfig = provider.get_required_service(AppConfig)
                backend_config_provider: IBackendConfigProvider = (
                    provider.get_required_service(cast(type, IBackendConfigProvider))
                )
                session_service: ISessionService = provider.get_required_service(
                    cast(type, ISessionService)
                )

                return BackendService(
                    backend_factory,
                    rate_limiter,
                    app_config,
                    session_service,
                    backend_config_provider=backend_config_provider,
                )

            services.add_singleton(
                BackendService, implementation_factory=backend_service_factory
            )

            services.add_singleton(
                cast(type, IBackendService),
                implementation_factory=backend_service_factory,
            )

            logger.debug("Registered backend service with all dependencies")
        except ImportError as e:
            logger.warning(f"Could not register backend service: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that backend services can be registered."""
        try:
            if not backend_registry.get_registered_backends():
                logger.warning("No backends registered in backend registry")

            return True
        except ImportError as e:
            logger.error(f"Backend services validation failed: {e}")
            return False
