"""
Health check initialization stage.

This stage registers and initializes health check services:
- Event bus for pub/sub
- Endpoint registry for tracking API URLs
- ICMP and HTTP health checkers
- Health state manager
- Health check scheduler
- Logging handler
"""

from __future__ import annotations

import logging
from typing import cast

import httpx

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

from .base import InitializationStage

logger = logging.getLogger(__name__)


class HealthCheckStage(InitializationStage):
    """
    Stage for registering health check services.

    This stage registers:
    - EventBus (if not already registered)
    - EndpointRegistry
    - ICMPHealthChecker
    - HTTPHealthChecker
    - HealthStateManager
    - HealthCheckScheduler
    - HealthLoggingHandler
    """

    @property
    def name(self) -> str:
        return "health_check"

    def get_dependencies(self) -> list[str]:
        # Depends on infrastructure (for httpx client) and backends
        return ["infrastructure", "backends"]

    def get_description(self) -> str:
        return "Register health check services for backend endpoint monitoring"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register health check services."""
        # Check if health checks are disabled
        if config.disable_health_checks or not config.health_check.enabled:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Health checks disabled by configuration (disable_health_checks=%s, health_check.enabled=%s)",
                    config.disable_health_checks,
                    config.health_check.enabled,
                )
            return

        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing health check services...")

        try:
            self._register_event_bus(services)
            self._register_endpoint_registry(services)
            self._register_health_checkers(services)
            self._register_state_manager(services)
            self._register_scheduler(services)
            self._register_logging_handler(services)
            self._register_backend_notifier(services)

            if logger.isEnabledFor(logging.INFO):
                logger.info("Health check services initialized successfully")

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Failed to initialize health check services: %s", e)
            raise

    def _register_event_bus(self, services: ServiceCollection) -> None:
        """Register the event bus."""
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.event_bus import EventBus

        def event_bus_factory(provider: IServiceProvider) -> EventBus:
            return EventBus()

        services.add_singleton(EventBus, implementation_factory=event_bus_factory)
        services.add_singleton(
            cast(type, IEventBus),
            implementation_factory=lambda p: p.get_required_service(EventBus),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered EventBus")

    def _register_endpoint_registry(self, services: ServiceCollection) -> None:
        """Register the endpoint registry."""
        from src.core.services.health.endpoint_registry import EndpointRegistry

        def registry_factory(provider: IServiceProvider) -> EndpointRegistry:
            return EndpointRegistry()

        services.add_singleton(
            EndpointRegistry, implementation_factory=registry_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered EndpointRegistry")

    def _register_health_checkers(self, services: ServiceCollection) -> None:
        """Register ICMP and HTTP health checkers."""
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.health.endpoint_registry import EndpointRegistry
        from src.core.services.health.http_checker import HTTPHealthChecker
        from src.core.services.health.icmp_checker import ICMPHealthChecker

        def icmp_checker_factory(provider: IServiceProvider) -> ICMPHealthChecker:
            event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))
            registry = provider.get_required_service(EndpointRegistry)
            config = provider.get_required_service(AppConfig)
            return ICMPHealthChecker(
                event_bus=event_bus,
                endpoint_registry=registry,
                config=config.health_check.ping,
            )

        def http_checker_factory(provider: IServiceProvider) -> HTTPHealthChecker:
            import contextlib

            event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))
            registry = provider.get_required_service(EndpointRegistry)
            config = provider.get_required_service(AppConfig)
            # Get shared HTTP client if available
            http_client: httpx.AsyncClient | None = None
            with contextlib.suppress(Exception):
                http_client = provider.get_service(httpx.AsyncClient)
            return HTTPHealthChecker(
                event_bus=event_bus,
                endpoint_registry=registry,
                config=config.health_check.http,
                http_client=http_client,
            )

        services.add_singleton(
            ICMPHealthChecker, implementation_factory=icmp_checker_factory
        )
        services.add_singleton(
            HTTPHealthChecker, implementation_factory=http_checker_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered ICMPHealthChecker and HTTPHealthChecker")

    def _register_state_manager(self, services: ServiceCollection) -> None:
        """Register the health state manager."""
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.health.endpoint_registry import EndpointRegistry
        from src.core.services.health.state_manager import HealthStateManager

        def state_manager_factory(provider: IServiceProvider) -> HealthStateManager:
            event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))
            registry = provider.get_required_service(EndpointRegistry)
            config = provider.get_required_service(AppConfig)
            return HealthStateManager(
                event_bus=event_bus,
                endpoint_registry=registry,
                config=config.health_check,
            )

        services.add_singleton(
            HealthStateManager, implementation_factory=state_manager_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered HealthStateManager")

    def _register_scheduler(self, services: ServiceCollection) -> None:
        """Register the health check scheduler."""
        from src.core.services.health.health_check_scheduler import HealthCheckScheduler
        from src.core.services.health.http_checker import HTTPHealthChecker
        from src.core.services.health.icmp_checker import ICMPHealthChecker

        def scheduler_factory(provider: IServiceProvider) -> HealthCheckScheduler:
            icmp_checker = provider.get_required_service(ICMPHealthChecker)
            http_checker = provider.get_required_service(HTTPHealthChecker)
            config = provider.get_required_service(AppConfig)
            return HealthCheckScheduler(
                icmp_checker=icmp_checker,
                http_checker=http_checker,
                config=config.health_check,
            )

        services.add_singleton(
            HealthCheckScheduler, implementation_factory=scheduler_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered HealthCheckScheduler")

    def _register_logging_handler(self, services: ServiceCollection) -> None:
        """Register the health logging handler."""
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.health.logging_handler import HealthLoggingHandler

        def logging_handler_factory(provider: IServiceProvider) -> HealthLoggingHandler:
            event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))
            config = provider.get_required_service(AppConfig)
            return HealthLoggingHandler(
                event_bus=event_bus,
                config=config.health_check,
            )

        services.add_singleton(
            HealthLoggingHandler, implementation_factory=logging_handler_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered HealthLoggingHandler")

    def _register_backend_notifier(self, services: ServiceCollection) -> None:
        """Register the backend health notifier."""
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.health.backend_notifier import BackendHealthNotifier
        from src.core.services.health.endpoint_registry import EndpointRegistry

        def backend_notifier_factory(
            provider: IServiceProvider,
        ) -> BackendHealthNotifier:
            event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))
            registry = provider.get_required_service(EndpointRegistry)
            config = provider.get_required_service(AppConfig)
            return BackendHealthNotifier(
                event_bus=event_bus,
                endpoint_registry=registry,
                config=config.health_check,
            )

        services.add_singleton(
            BackendHealthNotifier, implementation_factory=backend_notifier_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered BackendHealthNotifier")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that health check services can be registered."""
        if config.disable_health_checks or not config.health_check.enabled:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Health checks disabled, skipping validation")
            return True

        try:
            # Basic validation - just check imports are possible
            from src.core.services.health.backend_notifier import (  # noqa: F401
                BackendHealthNotifier,
            )
            from src.core.services.health.endpoint_registry import (  # noqa: F401
                EndpointRegistry,
            )
            from src.core.services.health.health_check_scheduler import (  # noqa: F401
                HealthCheckScheduler,
            )
            from src.core.services.health.http_checker import (  # noqa: F401
                HTTPHealthChecker,
            )
            from src.core.services.health.icmp_checker import (  # noqa: F401
                ICMPHealthChecker,
            )
            from src.core.services.health.logging_handler import (  # noqa: F401
                HealthLoggingHandler,
            )
            from src.core.services.health.state_manager import (  # noqa: F401
                HealthStateManager,
            )

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Health check services validation failed: %s", e)
            return False
