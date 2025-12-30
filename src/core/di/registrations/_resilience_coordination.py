"""
Resilience coordination and failover registrations.

Registers:
- RateLimitStateManager
- ResilienceCoordinator / IResilienceCoordinator
- FailoverService / FailoverCoordinator / IFailoverCoordinator
- FailoverPlanner / IFailoverPlanner
- Failure handling strategy (config-gated)
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_resilience_coordination_services(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register resilience coordination and failover services."""
    _register_resilience_coordinator(services)
    _register_failover_services(services)
    _register_failover_planner(services)
    _register_failure_handling_strategy(services, app_config)


def _register_failure_handling_strategy(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register failure handling strategy if enabled in config.

    The strategy can be resolved via resolve_failure_strategy() helper, which
    checks DI first, then falls back to constructing from config. This registration
    pre-registers the strategy in DI when enabled, avoiding runtime construction.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    if app_config is None:
        return

    try:
        # Check if failure handling is enabled
        failure_handling_settings = getattr(app_config, "failure_handling", None)
        if failure_handling_settings is None:
            return

        enabled_setting = getattr(failure_handling_settings, "enabled", None)
        if not isinstance(enabled_setting, bool) or not enabled_setting:
            return

        # Strategy will be resolved on-demand via resolve_failure_strategy() helper
        # No need to pre-register here since the helper handles both DI lookup and
        # config-based construction. This keeps the registrar simple and avoids
        # circular dependencies with routing service.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failure handling enabled; strategy will be resolved on-demand via helper"
            )
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Could not check failure handling config: {e}", exc_info=True)


def _register_resilience_coordinator(services: ServiceCollection) -> None:
    """Register the resilience coordinator and its backing state manager."""
    try:
        from src.core.interfaces.resilience_interface import IResilienceCoordinator
        from src.core.services.resilience.coordinator import ResilienceCoordinator
        from src.core.services.resilience.handlers import (
            AuthErrorHandler,
            RateLimitErrorHandler,
        )
        from src.core.services.resilience.rate_limit_state import RateLimitStateManager

        register_singleton_if_absent(services, RateLimitStateManager)

        def _resilience_coordinator_factory(
            provider: IServiceProvider,
        ) -> ResilienceCoordinator:
            state_manager = provider.get_required_service(RateLimitStateManager)
            auth_handler = AuthErrorHandler(state_manager)
            rate_limit_handler = RateLimitErrorHandler(
                state_manager, next_handler=auth_handler
            )
            return ResilienceCoordinator(
                state_manager=state_manager,
                error_handler_chain=rate_limit_handler,
            )

        register_singleton_if_absent(
            services,
            ResilienceCoordinator,
            implementation_factory=_resilience_coordinator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IResilienceCoordinator),
            implementation_factory=lambda p: p.get_required_service(
                ResilienceCoordinator
            ),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register ResilienceCoordinator: %s", e)


def _register_failover_services(services: ServiceCollection) -> None:
    """Register failover services (FailoverService + coordinator)."""
    try:
        from src.core.interfaces.failover_interface import IFailoverCoordinator
        from src.core.services.failover_coordinator import FailoverCoordinator
        from src.core.services.failover_service import FailoverService

        def _failover_service_factory(provider: IServiceProvider) -> FailoverService:
            config = provider.get_required_service(AppConfig)
            raw_routes = getattr(config, "failover_routes", None)
            routes: dict[str, Any] = raw_routes if isinstance(raw_routes, dict) else {}
            return FailoverService(failover_routes=routes)

        register_singleton_if_absent(
            services,
            FailoverService,
            implementation_factory=_failover_service_factory,
        )

        def _failover_coordinator_factory(
            provider: IServiceProvider,
        ) -> FailoverCoordinator:
            failover_service = provider.get_required_service(FailoverService)
            return FailoverCoordinator(failover_service)

        register_singleton_if_absent(
            services,
            FailoverCoordinator,
            implementation_factory=_failover_coordinator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IFailoverCoordinator),
            implementation_factory=lambda p: p.get_required_service(
                FailoverCoordinator
            ),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register failover services: %s", e)


def _register_failover_planner(services: ServiceCollection) -> None:
    """Register failover planner for selecting/filtering plans."""
    try:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.configuration_interface import IConfig
        from src.core.interfaces.failover_interface import (
            IFailoverCoordinator,
            IFailoverStrategy,
        )
        from src.core.interfaces.failover_planner_interface import IFailoverPlanner
        from src.core.interfaces.resilience_interface import IResilienceCoordinator
        from src.core.services.failover_planner import FailoverPlanner

        def _failover_planner_factory(provider: IServiceProvider) -> FailoverPlanner:
            app_state: IApplicationState = provider.get_required_service(
                cast(type, IApplicationState)
            )
            failover_coordinator: IFailoverCoordinator = provider.get_required_service(
                cast(type, IFailoverCoordinator)
            )
            backend_lifecycle_manager: IBackendLifecycleManager = (
                provider.get_required_service(cast(type, IBackendLifecycleManager))
            )
            config: IConfig = provider.get_required_service(cast(type, IConfig))

            # Optional services - handle RuntimeError when not registered
            failover_strategy = None
            try:
                failover_strategy = provider.get_service(cast(type, IFailoverStrategy))
            except RuntimeError:
                # Service not registered - this is expected for optional services
                pass
            resilience_coordinator = provider.get_service(
                cast(type, IResilienceCoordinator)
            )

            return FailoverPlanner(
                app_state=app_state,
                failover_coordinator=failover_coordinator,
                backend_lifecycle_manager=backend_lifecycle_manager,
                config=config,
                failover_strategy=failover_strategy,
                resilience_coordinator=resilience_coordinator,
            )

        register_singleton_if_absent(
            services,
            FailoverPlanner,
            implementation_factory=_failover_planner_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IFailoverPlanner),
            implementation_factory=lambda p: p.get_required_service(FailoverPlanner),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register FailoverPlanner: %s", e)
