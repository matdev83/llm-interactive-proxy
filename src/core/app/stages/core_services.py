"""
Core services initialization stage.

This stage registers fundamental services that have minimal dependencies:
- Configuration services
- Session management
- Logging utilities
- Basic repositories
"""

from __future__ import annotations

import contextlib
import logging

from src.core.app.middleware.tool_call_repair_middleware import ToolCallRepairMiddleware
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.tool_call_repair_service import ToolCallRepairService

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

        # Register ToolCallRepairService as a singleton with configured buffer cap
        def _tool_repair_factory(_: IServiceProvider) -> ToolCallRepairService:
            cap = 64 * 1024
            with contextlib.suppress(Exception):
                cap = int(config.session.tool_call_repair_buffer_cap_bytes)
            return ToolCallRepairService(max_buffer_bytes=cap)

        services.add_singleton(
            ToolCallRepairService, implementation_factory=_tool_repair_factory
        )
        logger.debug(
            "Registered ToolCallRepairService with cap=%d bytes",
            int(getattr(config.session, "tool_call_repair_buffer_cap_bytes", 65536)),
        )

        # Register ResponseProcessor as a singleton
        def response_processor_factory(provider: IServiceProvider) -> ResponseProcessor:
            processor = ResponseProcessor()
            if config.session.tool_call_repair_enabled:
                # Register ToolCallRepairMiddleware with the ResponseProcessor
                tool_call_repair_service = provider.get_required_service(
                    ToolCallRepairService
                )
                tool_call_middleware = ToolCallRepairMiddleware(
                    config, tool_call_repair_service
                )
                # Since register_middleware is async, we create a task for it.
                # The DI container does not directly support async factories for add_singleton.
                import asyncio

                task = asyncio.create_task(
                    processor.register_middleware(tool_call_middleware)
                )
                processor.add_background_task(task)  # Store the task
            return processor

        services.add_singleton(
            ResponseProcessor, implementation_factory=response_processor_factory
        )
        logger.debug("Registered ResponseProcessor with ToolCallRepairMiddleware")

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
        except ImportError as e:  # type: ignore[misc]
            logger.warning(f"Could not register session repository: {e}")

    def _register_session_service(self, services: ServiceCollection) -> None:
        """Register session service with dependency injection."""
        try:
            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.session_service_impl import SessionService

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
        except ImportError as e:  # type: ignore[misc]
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
            session_resolver: DefaultSessionResolver = DefaultSessionResolver(config)

            # Register as singleton instance
            services.add_instance(DefaultSessionResolver, session_resolver)
            from typing import cast

            services.add_instance(cast(type, ISessionResolver), session_resolver)

            logger.debug("Registered session resolver instance")

            from src.core.services.secure_state_service import SecureStateService

            # Register SecureStateService with a factory
            def secure_state_factory(provider: IServiceProvider) -> SecureStateService:
                app_state: IApplicationState = provider.get_required_service(
                    ApplicationStateService
                )
                return SecureStateService(app_state)

            services.add_singleton(
                SecureStateService, implementation_factory=secure_state_factory
            )
            logger.debug("Registered SecureStateService with factory")
        except ImportError as e:  # type: ignore[misc]
            logger.warning(
                f"Could not register session resolver or SecureStateService: {e}"
            )

        # Register core services from DI services module
        try:
            from src.core.di.services import register_core_services

            register_core_services(services, config)
            logger.debug("Registered core services from DI module")
        except Exception as e:
            logger.error(f"Failed to register core services from DI module: {e}")
            raise

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that core services can be registered."""
        try:
            # Check that required modules are available

            # Validate config is not None
            if config is None:
                logger.error("AppConfig is None")
                return False

            return True
        except ImportError as e:  # type: ignore[misc]
            logger.error(f"Core services validation failed: {e}")
            return False
