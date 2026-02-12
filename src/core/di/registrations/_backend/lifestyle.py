"""
Backend lifecycle and resolution registration helpers.

Handles registration of:
- Backend Lifecycle Manager
- Backend Model Resolver
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_lifecycle_manager(services: ServiceCollection) -> None:
    """Register BackendLifecycleManager for backend instance management."""
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )
    from src.core.interfaces.backend_lifecycle_manager_interface import (
        IBackendLifecycleManager,
    )
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_lifecycle_manager import BackendLifecycleManager

    def _backend_lifecycle_manager_factory(
        provider: IServiceProvider,
    ) -> BackendLifecycleManager:
        config = provider.get_service(cast(type, IConfig))
        backend_factory = provider.get_service(BackendFactory)
        backend_config_provider = provider.get_service(
            cast(type, IBackendConfigProvider)
        )

        per_session_limit = 32
        global_backend_limit = 200
        try:
            app_config = provider.get_service(AppConfig)
            if app_config is not None:
                per_session_limit_raw = getattr(
                    app_config.session, "max_per_session_backends", 32
                )
                global_backend_limit_raw = getattr(
                    app_config.session, "max_global_backends", 200
                )
                per_session_limit = int(per_session_limit_raw or 32)
                global_backend_limit = int(global_backend_limit_raw or 200)
        except (AttributeError, TypeError, ValueError) as exc:
            # Expected errors when reading config values:
            # AttributeError: session attribute or nested attributes missing
            # TypeError: getattr returns wrong type or int() receives wrong type
            # ValueError: int() receives invalid value
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get backend lifecycle limits from AppConfig (%s); using defaults",
                    type(exc).__name__,
                    exc_info=True,
                )
            per_session_limit = 32
            global_backend_limit = 200
        except Exception as exc:
            # Unexpected exception - log with full context
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error reading backend lifecycle limits from AppConfig (%s); using defaults",
                    type(exc).__name__,
                    exc_info=True,
                )
            per_session_limit = 32
            global_backend_limit = 200

        return BackendLifecycleManager(
            factory=backend_factory,
            config=config,
            backend_config_provider=backend_config_provider,
            per_session_limit=per_session_limit,
            global_backend_limit=global_backend_limit,
        )

    register_singleton_if_absent(
        services,
        BackendLifecycleManager,
        implementation_factory=_backend_lifecycle_manager_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IBackendLifecycleManager),
        implementation_factory=lambda p: p.get_required_service(
            BackendLifecycleManager
        ),
    )


def register_backend_model_resolver(services: ServiceCollection) -> None:
    """Register BackendModelResolver for backend/model resolution."""
    from src.core.interfaces.backend_lifecycle_manager_interface import (
        IBackendLifecycleManager,
    )
    from src.core.interfaces.backend_model_resolver_interface import (
        IBackendModelResolver,
    )
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.interfaces.model_alias_resolver_interface import (
        IModelAliasResolver,
    )
    from src.core.interfaces.planning_phase_manager_interface import (
        IPlanningPhaseManager,
    )
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.services.backend_model_resolver import BackendModelResolver
    from src.core.services.backend_routing_service import BackendRoutingService

    def _backend_model_resolver_factory(
        provider: IServiceProvider,
    ) -> BackendModelResolver:
        session_service: ISessionService = provider.get_required_service(
            cast(type, ISessionService)
        )
        model_alias_resolver: IModelAliasResolver = provider.get_required_service(
            cast(type, IModelAliasResolver)
        )
        planning_phase_manager: IPlanningPhaseManager = provider.get_required_service(
            cast(type, IPlanningPhaseManager)
        )
        backend_lifecycle_manager: IBackendLifecycleManager = (
            provider.get_required_service(cast(type, IBackendLifecycleManager))
        )
        config: IConfig = provider.get_required_service(cast(type, IConfig))
        routing_service: BackendRoutingService = provider.get_required_service(
            BackendRoutingService
        )
        return BackendModelResolver(
            session_service=session_service,
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase_manager,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=config,
            routing_service=routing_service,
        )

    register_singleton_if_absent(
        services,
        BackendModelResolver,
        implementation_factory=_backend_model_resolver_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IBackendModelResolver),
        implementation_factory=lambda p: p.get_required_service(BackendModelResolver),
    )


def register_backend_reactivation_control(services: ServiceCollection) -> None:
    """Register BackendReactivationControl for explicit runtime reactivation."""
    from src.core.interfaces.backend_lifecycle_manager_interface import (
        IBackendLifecycleManager,
    )
    from src.core.interfaces.resilience_interface import IResilienceCoordinator
    from src.core.services.backend_reactivation_control import (
        BackendReactivationControl,
    )

    def _backend_reactivation_control_factory(
        provider: IServiceProvider,
    ) -> BackendReactivationControl:
        backend_lifecycle_manager: IBackendLifecycleManager = (
            provider.get_required_service(cast(type, IBackendLifecycleManager))
        )
        resilience_coordinator: IResilienceCoordinator | None = provider.get_service(
            cast(type, IResilienceCoordinator)
        )
        return BackendReactivationControl(
            backend_lifecycle_manager=backend_lifecycle_manager,
            resilience_coordinator=resilience_coordinator,
        )

    register_singleton_if_absent(
        services,
        BackendReactivationControl,
        implementation_factory=_backend_reactivation_control_factory,
    )
