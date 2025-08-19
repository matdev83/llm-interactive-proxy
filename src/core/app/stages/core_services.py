"""
Core services initialization stage.

This stage registers fundamental services that have minimal dependencies:
- Configuration services
- Session management
- Logging utilities
- Basic repositories
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

from .base import InitializationStage

logger = logging.getLogger(__name__)


class CoreServicesStage(InitializationStage):
    """
    Stage for registering core services with minimal dependencies.

    This stage registers:
    - AppConfig as a singleton instance
    - Session repository and service
    - Session resolver
    - Basic logging and configuration services
    """

    @property
    def name(self) -> str:
        return "core_services"

    def get_description(self) -> str:
        return "Register core services (config, session, logging)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register core services that have no external dependencies."""
        logger.info("Initializing core services...")

        # Register AppConfig as singleton instance
        services.add_instance(AppConfig, config)
        logger.debug("Registered AppConfig instance")

        # Register session repository
        self._register_session_repository(services)

        # Register session service
        self._register_session_service(services)

        # Register session resolver
        self._register_session_resolver(services, config)

        logger.info("Core services initialized successfully")

    def _register_session_repository(self, services: ServiceCollection) -> None:
        """Register session repository services."""
        try:
            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.repositories.in_memory_session_repository import (
                InMemorySessionRepository,
            )

            # Register concrete implementation
            services.add_singleton(InMemorySessionRepository)

            # Register interface binding
            from typing import cast

            services.add_singleton(
                cast(type, ISessionRepository), InMemorySessionRepository
            )

            logger.debug("Registered session repository services")
        except ImportError as e:
            logger.warning(f"Could not register session repository: {e}")

    def _register_session_service(self, services: ServiceCollection) -> None:
        """Register session service with dependency injection."""
        try:
            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.session_service import SessionService

            def session_service_factory(provider: IServiceProvider) -> SessionService:
                """Factory function for creating SessionService with dependencies."""
                from typing import cast

                repo: ISessionRepository = provider.get_required_service(
                    cast(type, ISessionRepository)
                )
                return SessionService(repo)

            # Register concrete implementation with factory
            services.add_singleton(
                SessionService, implementation_factory=session_service_factory
            )

            # Register interface binding with same factory
            from typing import cast

            services.add_singleton(
                cast(type, ISessionService),
                implementation_factory=session_service_factory,
            )

            logger.debug("Registered session service with factory")
        except ImportError as e:
            logger.warning(f"Could not register session service: {e}")

    def _register_session_resolver(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register session resolver as singleton instance."""
        try:
            from src.core.interfaces.session_resolver_interface import ISessionResolver
            from src.core.services.session_resolver_service import (
                DefaultSessionResolver,
            )

            # Create instance with config
            session_resolver = DefaultSessionResolver(config)

            # Register as singleton instance
            services.add_instance(DefaultSessionResolver, session_resolver)
            from typing import cast

            services.add_instance(cast(type, ISessionResolver), session_resolver)

            logger.debug("Registered session resolver instance")
        except ImportError as e:
            logger.warning(f"Could not register session resolver: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that core services can be registered."""
        try:
            # Check that required modules are available

            # Validate config is not None
            if config is None:
                logger.error("AppConfig is None")
                return False

            return True
        except ImportError as e:
            logger.error(f"Core services validation failed: {e}")
            return False
