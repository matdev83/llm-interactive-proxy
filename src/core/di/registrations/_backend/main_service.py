"""
Backend main service registration helpers.

Handles registration of:
- Backend Service
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_service(services: ServiceCollection) -> None:
    """Register BackendService and IBackendService binding."""
    try:
        import contextlib

        from src.core.interfaces.backend_completion_flow_interface import (
            IBackendCompletionFlow,
        )
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )
        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.backend_model_resolver_interface import (
            IBackendModelResolver,
        )
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.failover_interface import IFailoverCoordinator
        from src.core.interfaces.failover_planner_interface import IFailoverPlanner
        from src.core.interfaces.model_alias_resolver_interface import (
            IModelAliasResolver,
        )
        from src.core.interfaces.planning_phase_manager_interface import (
            IPlanningPhaseManager,
        )
        from src.core.interfaces.reasoning_config_applicator_interface import (
            IReasoningConfigApplicator,
        )
        from src.core.interfaces.session_service_interface import ISessionService
        from src.core.interfaces.stream_formatting_interface import (
            IStreamFormattingService,
        )
        from src.core.interfaces.stream_session_id_resolver_interface import (
            IStreamSessionIdResolver,
        )
        from src.core.interfaces.uri_parameter_applicator_interface import (
            IURIParameterApplicator,
        )
        from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
        from src.core.interfaces.usage_tracking_wrapper_interface import (
            IUsageTrackingWrapper,
        )
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.backend_factory import BackendFactory
        from src.core.services.backend_routing_service import BackendRoutingService
        from src.core.services.backend_service import BackendService
        from src.core.services.rate_limiter import RateLimiter
        from src.core.services.resilience.coordinator import ResilienceCoordinator

        def _backend_service_factory(provider: IServiceProvider) -> BackendService:
            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )
            from src.core.interfaces.configuration_interface import IConfig
            from src.core.interfaces.failure_strategy_interface import (
                IFailureHandlingStrategy,
            )

            backend_factory: BackendFactory = provider.get_required_service(
                BackendFactory
            )
            rate_limiter: RateLimiter = provider.get_required_service(RateLimiter)
            config: IConfig = provider.get_required_service(cast(type, IConfig))

            session_service: ISessionService = provider.get_required_service(
                cast(type, ISessionService)
            )
            app_state: IApplicationState = provider.get_required_service(
                cast(type, IApplicationState)
            )
            backend_config_provider: IBackendConfigProvider = (
                provider.get_required_service(cast(type, IBackendConfigProvider))
            )

            failover_coordinator = provider.get_service(
                cast(type, IFailoverCoordinator)
            )

            failover_strategy = None
            with contextlib.suppress(Exception):
                if (
                    app_state.get_use_failover_strategy()
                    and failover_coordinator is not None
                ):
                    from src.core.services.failover_strategy import (
                        DefaultFailoverStrategy,
                    )

                    failover_strategy = DefaultFailoverStrategy(failover_coordinator)

            wire_capture: IWireCapture | None = provider.get_service(
                cast(type, IWireCapture)
            )
            routing_service: BackendRoutingService | None = provider.get_service(
                BackendRoutingService
            )
            resilience_coordinator: ResilienceCoordinator | None = provider.get_service(
                ResilienceCoordinator
            )

            from src.core.di.registration_helpers.failure_handling import (
                resolve_failure_strategy,
            )

            failure_handling_strategy: IFailureHandlingStrategy | None = (
                resolve_failure_strategy(provider, config, routing_service)
            )
            # Optional service - handle RuntimeError when not registered
            usage_tracking_service: IUsageTrackingService | None = None
            with contextlib.suppress(RuntimeError):
                # Service not registered - this is expected for optional services
                usage_tracking_service = provider.get_service(
                    cast(type, IUsageTrackingService)
                )

            stream_formatting_service: IStreamFormattingService = (
                provider.get_required_service(cast(type, IStreamFormattingService))
            )
            usage_tracking_wrapper: IUsageTrackingWrapper = (
                provider.get_required_service(cast(type, IUsageTrackingWrapper))
            )
            model_alias_resolver: IModelAliasResolver = provider.get_required_service(
                cast(type, IModelAliasResolver)
            )
            exception_normalizer: IExceptionNormalizer = provider.get_required_service(
                cast(type, IExceptionNormalizer)
            )
            backend_lifecycle_manager: IBackendLifecycleManager = (
                provider.get_required_service(cast(type, IBackendLifecycleManager))
            )
            planning_phase_manager: IPlanningPhaseManager = (
                provider.get_required_service(cast(type, IPlanningPhaseManager))
            )
            reasoning_config_applicator: IReasoningConfigApplicator = (
                provider.get_required_service(cast(type, IReasoningConfigApplicator))
            )
            uri_parameter_applicator: IURIParameterApplicator = (
                provider.get_required_service(cast(type, IURIParameterApplicator))
            )
            stream_session_id_resolver: IStreamSessionIdResolver = (
                provider.get_required_service(cast(type, IStreamSessionIdResolver))
            )
            backend_model_resolver: IBackendModelResolver = (
                provider.get_required_service(cast(type, IBackendModelResolver))
            )
            failover_planner: IFailoverPlanner = provider.get_required_service(
                cast(type, IFailoverPlanner)
            )
            backend_completion_flow: IBackendCompletionFlow = (
                provider.get_required_service(cast(type, IBackendCompletionFlow))
            )

            failover_routes: dict[str, dict[str, Any]] | None = None
            with contextlib.suppress(Exception):
                app_config = provider.get_service(AppConfig)
                if app_config is not None:
                    raw = getattr(app_config, "failover_routes", None)
                    if isinstance(raw, dict):
                        failover_routes = cast(dict[str, dict[str, Any]], raw)

            return BackendService(  # DI-bypass (factory construction)
                backend_factory,
                rate_limiter,
                config,
                session_service,
                app_state,
                backend_config_provider=backend_config_provider,
                stream_formatting_service=stream_formatting_service,
                usage_tracking_wrapper=usage_tracking_wrapper,
                model_alias_resolver=model_alias_resolver,
                exception_normalizer=exception_normalizer,
                backend_lifecycle_manager=backend_lifecycle_manager,
                planning_phase_manager=planning_phase_manager,
                reasoning_config_applicator=reasoning_config_applicator,
                uri_parameter_applicator=uri_parameter_applicator,
                stream_session_id_resolver=stream_session_id_resolver,
                backend_model_resolver=backend_model_resolver,
                failover_planner=failover_planner,
                backend_completion_flow=backend_completion_flow,
                failover_routes=failover_routes,
                failover_strategy=failover_strategy,
                failover_coordinator=failover_coordinator,
                wire_capture=wire_capture,
                routing_service=routing_service,
                resilience_coordinator=resilience_coordinator,
                failure_handling_strategy=failure_handling_strategy,
                usage_tracking_service=usage_tracking_service,
            )

        register_singleton_if_absent(
            services,
            BackendService,
            implementation_factory=_backend_service_factory,
        )

        register_singleton_if_absent(
            services,
            cast(type, IBackendService),
            implementation_factory=lambda p: p.get_required_service(BackendService),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register BackendService: %s", e)
