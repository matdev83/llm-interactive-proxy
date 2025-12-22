"""
Resilience registrar.

Registers failover, rate limiting, failure strategy, and backend completion flow services.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def _create_eos_adapter(provider: IServiceProvider) -> Any | None:
    """Create EoS adapter if available and enabled (optional dependency)."""
    try:
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.end_of_session_service_interface import (
            IEndOfSessionService,
        )
        from src.core.services.backend_completion_flow.eos_adapter import (
            BackendCompletionFlowEosAdapter,
        )

        eos_service = provider.get_service(cast(type, IEndOfSessionService))  # type: ignore[type-abstract]
        if eos_service is not None:
            config = provider.get_required_service(AppConfig)
            eos_config = config.end_of_session
            if eos_config.enabled:
                return BackendCompletionFlowEosAdapter(
                    end_of_session_service=eos_service,
                    config=eos_config,
                )
    except ImportError:
        pass
    return None


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register resilience services.

    This registrar handles:
    - Failure handling strategies (optional, based on config)
    - Rate limiting (registered in infrastructure stage)
    - Failover coordination (optional)
    - Backend completion flow collaborators (registered in core)

    Note: Many resilience services are registered elsewhere (e.g., RateLimiter in
    InfrastructureStage, BackendCompletionFlow in core registrar). This registrar
    focuses on failure handling strategy registration when enabled.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    _register_resilience_coordinator(services)
    _register_failover_services(services)
    _register_failover_planner(services)
    _register_backend_completion_flow(services)
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
        from src.core.services.resilience.rate_limit_state import RateLimitStateManager

        register_singleton_if_absent(services, RateLimitStateManager)

        def _resilience_coordinator_factory(
            provider: IServiceProvider,
        ) -> ResilienceCoordinator:
            state_manager = provider.get_required_service(RateLimitStateManager)
            return ResilienceCoordinator(state_manager=state_manager)

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

            failover_strategy = provider.get_service(cast(type, IFailoverStrategy))
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


def _register_backend_completion_flow(services: ServiceCollection) -> None:
    """Register BackendCompletionFlow orchestrator and collaborators."""
    try:
        from src.core.interfaces.backend_completion_collaborators import (
            IBackendAvailabilityChecker,
            IBackendInvoker,
            IBackendRequestPreparer,
            ICompletionSessionResolver,
            IFailureRecoveryExecutor,
            IUsageAccountingOrchestrator,
            IWireCaptureOrchestrator,
        )
        from src.core.interfaces.backend_completion_flow_interface import (
            IBackendCompletionFlow,
        )
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )
        from src.core.interfaces.backend_factory_interface import IBackendFactory
        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.backend_model_resolver_interface import (
            IBackendModelResolver,
        )
        from src.core.interfaces.configuration_interface import IConfig
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.failover_planner_interface import IFailoverPlanner
        from src.core.interfaces.failure_strategy_interface import (
            IFailureHandlingStrategy,
        )
        from src.core.interfaces.planning_phase_manager_interface import (
            IPlanningPhaseManager,
        )
        from src.core.interfaces.resilience_interface import IResilienceCoordinator
        from src.core.interfaces.stream_formatting_interface import (
            IStreamFormattingService,
        )
        from src.core.interfaces.stream_session_id_resolver_interface import (
            IStreamSessionIdResolver,
        )
        from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
        from src.core.interfaces.usage_tracking_wrapper_interface import (
            IUsageTrackingWrapper,
        )
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.backend_completion_flow.availability_checker import (
            BackendAvailabilityChecker,
        )
        from src.core.services.backend_completion_flow.backend_manager import (
            BackendManager,
        )
        from src.core.services.backend_completion_flow.backend_request_preparer import (
            BackendRequestPreparer,
        )
        from src.core.services.backend_completion_flow.completion_session_resolver import (
            CompletionSessionResolver,
        )
        from src.core.services.backend_completion_flow.failure_recovery_executor import (
            FailureRecoveryExecutor,
        )
        from src.core.services.backend_completion_flow.service import (
            BackendCompletionFlow,
        )
        from src.core.services.backend_completion_flow.usage_accounting_orchestrator import (
            UsageAccountingOrchestrator,
        )
        from src.core.services.backend_completion_flow.wire_capture_orchestrator import (
            WireCaptureOrchestrator,
        )
        from src.core.services.backend_routing_service import BackendRoutingService

        def _get_failover_routes(
            provider: IServiceProvider,
        ) -> dict[str, dict[str, Any]]:
            config = provider.get_service(AppConfig)
            raw = (
                getattr(config, "failover_routes", None) if config is not None else None
            )
            if isinstance(raw, dict):
                return cast(dict[str, dict[str, Any]], raw)
            return {}

        def _availability_checker_factory(
            provider: IServiceProvider,
        ) -> BackendAvailabilityChecker:
            backend_lifecycle_manager: IBackendLifecycleManager = (
                provider.get_required_service(cast(type, IBackendLifecycleManager))
            )
            resilience_coordinator: IResilienceCoordinator | None = (
                provider.get_service(cast(type, IResilienceCoordinator))
            )
            return BackendAvailabilityChecker(
                backend_lifecycle_manager=backend_lifecycle_manager,
                resilience_coordinator=resilience_coordinator,
                failover_routes=_get_failover_routes(provider),
            )

        register_singleton_if_absent(
            services,
            BackendAvailabilityChecker,
            implementation_factory=_availability_checker_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IBackendAvailabilityChecker),
            implementation_factory=lambda p: p.get_required_service(
                BackendAvailabilityChecker
            ),
        )

        def _completion_session_resolver_factory(
            provider: IServiceProvider,
        ) -> CompletionSessionResolver:
            from src.core.interfaces.session_service_interface import ISessionService

            session_service: ISessionService = provider.get_required_service(
                cast(type, ISessionService)
            )
            return CompletionSessionResolver(session_service=session_service)

        register_singleton_if_absent(
            services,
            CompletionSessionResolver,
            implementation_factory=_completion_session_resolver_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, ICompletionSessionResolver),
            implementation_factory=lambda p: p.get_required_service(
                CompletionSessionResolver
            ),
        )

        def _backend_request_preparer_factory(
            provider: IServiceProvider,
        ) -> BackendRequestPreparer:
            from src.core.interfaces.reasoning_config_applicator_interface import (
                IReasoningConfigApplicator,
            )
            from src.core.interfaces.uri_parameter_applicator_interface import (
                IURIParameterApplicator,
            )

            backend_model_resolver: IBackendModelResolver = (
                provider.get_required_service(cast(type, IBackendModelResolver))
            )
            backend_config_provider: IBackendConfigProvider = (
                provider.get_required_service(cast(type, IBackendConfigProvider))
            )
            reasoning_config_applicator: IReasoningConfigApplicator = (
                provider.get_required_service(cast(type, IReasoningConfigApplicator))
            )
            uri_parameter_applicator: IURIParameterApplicator = (
                provider.get_required_service(cast(type, IURIParameterApplicator))
            )
            config: IConfig = provider.get_required_service(cast(type, IConfig))
            return BackendRequestPreparer(
                backend_model_resolver=backend_model_resolver,
                backend_config_service=backend_config_provider,
                reasoning_config_applicator=reasoning_config_applicator,
                uri_parameter_applicator=uri_parameter_applicator,
                config=config,
            )

        register_singleton_if_absent(
            services,
            BackendRequestPreparer,
            implementation_factory=_backend_request_preparer_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IBackendRequestPreparer),
            implementation_factory=lambda p: p.get_required_service(
                BackendRequestPreparer
            ),
        )

        def _backend_manager_factory(provider: IServiceProvider) -> BackendManager:
            backend_lifecycle_manager: IBackendLifecycleManager = (
                provider.get_required_service(cast(type, IBackendLifecycleManager))
            )
            resilience_coordinator: IResilienceCoordinator | None = (
                provider.get_service(cast(type, IResilienceCoordinator))
            )
            return BackendManager(
                backend_lifecycle_manager=backend_lifecycle_manager,
                resilience_coordinator=resilience_coordinator,
                failover_routes=_get_failover_routes(provider),
            )

        register_singleton_if_absent(
            services,
            BackendManager,
            implementation_factory=_backend_manager_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IBackendInvoker),
            implementation_factory=lambda p: p.get_required_service(BackendManager),
        )

        def _failure_recovery_executor_factory(
            provider: IServiceProvider,
        ) -> FailureRecoveryExecutor:
            failover_planner: IFailoverPlanner = provider.get_required_service(
                cast(type, IFailoverPlanner)
            )
            failure_strategy: IFailureHandlingStrategy | None = provider.get_service(
                cast(type, IFailureHandlingStrategy)
            )
            routing_service: BackendRoutingService | None = provider.get_service(
                BackendRoutingService
            )
            config: IConfig = provider.get_required_service(cast(type, IConfig))
            return FailureRecoveryExecutor(
                failover_planner=failover_planner,
                failure_handling_strategy=failure_strategy,
                routing_service=routing_service,
                config=config,
                failover_routes=_get_failover_routes(provider),
            )

        register_singleton_if_absent(
            services,
            FailureRecoveryExecutor,
            implementation_factory=_failure_recovery_executor_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IFailureRecoveryExecutor),
            implementation_factory=lambda p: p.get_required_service(
                FailureRecoveryExecutor
            ),
        )

        def _wire_capture_orchestrator_factory(
            provider: IServiceProvider,
        ) -> WireCaptureOrchestrator:
            wire_capture: IWireCapture | None = provider.get_service(
                cast(type, IWireCapture)
            )
            config: IConfig = provider.get_required_service(cast(type, IConfig))
            backend_config_provider: IBackendConfigProvider = (
                provider.get_required_service(cast(type, IBackendConfigProvider))
            )
            return WireCaptureOrchestrator(
                wire_capture=wire_capture,
                config=config,
                backend_config_service=backend_config_provider,
            )

        register_singleton_if_absent(
            services,
            WireCaptureOrchestrator,
            implementation_factory=_wire_capture_orchestrator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IWireCaptureOrchestrator),
            implementation_factory=lambda p: p.get_required_service(
                WireCaptureOrchestrator
            ),
        )

        def _usage_accounting_orchestrator_factory(
            provider: IServiceProvider,
        ) -> UsageAccountingOrchestrator:
            usage_tracking_service: IUsageTrackingService | None = provider.get_service(
                cast(type, IUsageTrackingService)
            )
            usage_tracking_wrapper: IUsageTrackingWrapper = (
                provider.get_required_service(cast(type, IUsageTrackingWrapper))
            )
            stream_session_id_resolver: IStreamSessionIdResolver = (
                provider.get_required_service(cast(type, IStreamSessionIdResolver))
            )
            planning_phase_manager: IPlanningPhaseManager = (
                provider.get_required_service(cast(type, IPlanningPhaseManager))
            )
            resilience_coordinator: IResilienceCoordinator | None = (
                provider.get_service(cast(type, IResilienceCoordinator))
            )
            backend_factory: IBackendFactory | None = provider.get_service(
                cast(type, IBackendFactory)
            )
            backend_lifecycle_manager: IBackendLifecycleManager | None = (
                provider.get_service(cast(type, IBackendLifecycleManager))
            )
            from src.core.interfaces.usage_normalization_service_interface import (
                IUsageNormalizationService,
            )

            usage_normalization_service: IUsageNormalizationService | None = (
                provider.get_service(cast(type, IUsageNormalizationService))
            )
            wire_capture_orch = provider.get_service(
                cast(type, IWireCaptureOrchestrator)
            )
            return UsageAccountingOrchestrator(
                usage_tracking_service=usage_tracking_service,
                usage_tracking_wrapper=usage_tracking_wrapper,
                stream_session_id_resolver=stream_session_id_resolver,
                planning_phase_manager=planning_phase_manager,
                resilience_coordinator=resilience_coordinator,
                backend_factory=backend_factory,
                backend_lifecycle_manager=backend_lifecycle_manager,
                usage_normalization_service=usage_normalization_service,
                wire_capture_orchestrator=wire_capture_orch,
            )

        register_singleton_if_absent(
            services,
            UsageAccountingOrchestrator,
            implementation_factory=_usage_accounting_orchestrator_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IUsageAccountingOrchestrator),
            implementation_factory=lambda p: p.get_required_service(
                UsageAccountingOrchestrator
            ),
        )

        def _backend_completion_flow_factory(
            provider: IServiceProvider,
        ) -> BackendCompletionFlow:
            availability_checker: IBackendAvailabilityChecker = (
                provider.get_required_service(cast(type, IBackendAvailabilityChecker))
            )
            request_preparer: IBackendRequestPreparer = provider.get_required_service(
                cast(type, IBackendRequestPreparer)
            )
            session_resolver: ICompletionSessionResolver = (
                provider.get_required_service(cast(type, ICompletionSessionResolver))
            )
            backend_invoker: IBackendInvoker = provider.get_required_service(
                cast(type, IBackendInvoker)
            )
            failover_executor: IFailureRecoveryExecutor = provider.get_required_service(
                cast(type, IFailureRecoveryExecutor)
            )
            wire_capture_orchestrator: IWireCaptureOrchestrator = (
                provider.get_required_service(cast(type, IWireCaptureOrchestrator))
            )
            usage_accounting_orchestrator: IUsageAccountingOrchestrator = (
                provider.get_required_service(cast(type, IUsageAccountingOrchestrator))
            )
            exception_normalizer: IExceptionNormalizer = provider.get_required_service(
                cast(type, IExceptionNormalizer)
            )
            stream_formatting_service: IStreamFormattingService = (
                provider.get_required_service(cast(type, IStreamFormattingService))
            )
            resilience_coordinator: IResilienceCoordinator | None = (
                provider.get_service(cast(type, IResilienceCoordinator))
            )
            eos_adapter = _create_eos_adapter(provider)

            return BackendCompletionFlow(
                availability_checker=availability_checker,
                request_preparer=request_preparer,
                session_resolver=session_resolver,
                backend_invoker=backend_invoker,
                failover_executor=failover_executor,
                wire_capture_orchestrator=wire_capture_orchestrator,
                usage_accounting_orchestrator=usage_accounting_orchestrator,
                exception_normalizer=exception_normalizer,
                stream_formatting_service=stream_formatting_service,
                resilience_coordinator=resilience_coordinator,
                eos_adapter=eos_adapter,
            )

        register_singleton_if_absent(
            services,
            BackendCompletionFlow,
            implementation_factory=_backend_completion_flow_factory,
        )
        register_singleton_if_absent(
            services,
            cast(type, IBackendCompletionFlow),
            implementation_factory=lambda p: p.get_required_service(
                BackendCompletionFlow
            ),
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register BackendCompletionFlow wiring: %s", e)
