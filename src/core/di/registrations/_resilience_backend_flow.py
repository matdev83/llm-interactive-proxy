"""
Backend completion flow registrations.

Registers all BackendCompletionFlow collaborators:
- BackendAvailabilityChecker / IBackendAvailabilityChecker
- CompletionSessionResolver / ICompletionSessionResolver
- BackendRequestPreparer / IBackendRequestPreparer
- BackendManager / IBackendInvoker
- FailureRecoveryExecutor / IFailureRecoveryExecutor
- WireCaptureOrchestrator / IWireCaptureOrchestrator
- UsageAccountingOrchestrator / IUsageAccountingOrchestrator
- BackendCompletionFlow / IBackendCompletionFlow
- BackendCompletionFlowEosAdapter (optional)
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_backend_completion_flow_services(services: ServiceCollection) -> None:
    """Register backend completion flow and all collaborators."""
    _register_backend_completion_flow(services)


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
            from src.core.services.auxiliary_request_router import (
                AuxiliaryRequestRouter,
            )
            from src.core.services.auxiliary_request_router import (
                AuxiliaryRoutingConfig as AuxRoutingConfigDomain,
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

            # Create auxiliary request router if configured
            auxiliary_router: AuxiliaryRequestRouter | None = None
            try:
                aux_config = getattr(config, "auxiliary_routing", None)
                if aux_config and getattr(aux_config, "enabled", False):
                    # Convert pydantic config to domain config
                    domain_config = AuxRoutingConfigDomain(
                        enabled=aux_config.enabled,
                        backend=getattr(aux_config, "backend", None),
                        model=getattr(aux_config, "model", None),
                        detection_patterns=list(
                            getattr(aux_config, "detection_patterns", [])
                        ),
                        max_message_count=getattr(aux_config, "max_message_count", 3),
                    )
                    auxiliary_router = AuxiliaryRequestRouter(domain_config)
                    logger.info(
                        "Auxiliary request routing enabled: backend=%s, model=%s",
                        domain_config.backend,
                        domain_config.model,
                    )
            except Exception as e:
                logger.warning("Failed to initialize auxiliary request router: %s", e)

            return BackendRequestPreparer(
                backend_model_resolver=backend_model_resolver,
                backend_config_service=backend_config_provider,
                reasoning_config_applicator=reasoning_config_applicator,
                uri_parameter_applicator=uri_parameter_applicator,
                config=config,
                auxiliary_router=auxiliary_router,
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
            import contextlib

            # Optional service - handle RuntimeError when not registered
            failure_strategy: IFailureHandlingStrategy | None = None
            with contextlib.suppress(RuntimeError):
                # Service not registered - this is expected for optional services
                failure_strategy = provider.get_service(
                    cast(type, IFailureHandlingStrategy)
                )
            routing_service = provider.get_service(BackendRoutingService)
            config: IConfig = provider.get_required_service(cast(type, IConfig))

            # Get cancellation coordinator (optional, registered in streaming phase)
            from src.core.interfaces.session_cancellation_coordinator_interface import (
                ISessionCancellationCoordinator,
            )

            cancellation_coordinator = provider.get_service(
                cast(type, ISessionCancellationCoordinator)
            )

            return FailureRecoveryExecutor(
                failover_planner=failover_planner,
                failure_handling_strategy=failure_strategy,
                routing_service=routing_service,
                config=config,
                failover_routes=_get_failover_routes(provider),
                cancellation_coordinator=cancellation_coordinator,
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
            import contextlib

            # Optional service - handle RuntimeError when not registered
            usage_tracking_service: IUsageTrackingService | None = None
            with contextlib.suppress(RuntimeError):
                # Service not registered - this is expected for optional services
                usage_tracking_service = provider.get_service(
                    cast(type, IUsageTrackingService)
                )
            # Wrapper is always registered (factory handles None services)
            usage_tracking_wrapper: IUsageTrackingWrapper = (
                provider.get_required_service(cast(type, IUsageTrackingWrapper))
            )
            stream_session_id_resolver: IStreamSessionIdResolver = (
                provider.get_required_service(cast(type, IStreamSessionIdResolver))
            )
            planning_phase_manager: IPlanningPhaseManager = (
                provider.get_required_service(cast(type, IPlanningPhaseManager))
            )
            resilience_coordinator = provider.get_service(
                cast(type, IResilienceCoordinator)
            )
            backend_factory = provider.get_service(cast(type, IBackendFactory))
            backend_lifecycle_manager = provider.get_service(
                cast(type, IBackendLifecycleManager)
            )
            from src.core.interfaces.usage_normalization_service_interface import (
                IUsageNormalizationService,
            )

            usage_normalization_service = provider.get_service(
                cast(type, IUsageNormalizationService)
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

        # Register ConnectorInvoker as singleton (no dependencies)
        from src.core.services.connector_invoker import ConnectorInvoker

        register_singleton_if_absent(
            services,
            ConnectorInvoker,
            implementation_factory=lambda p: ConnectorInvoker(),
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
            connector_invoker: ConnectorInvoker = provider.get_required_service(
                ConnectorInvoker
            )
            resilience_coordinator = provider.get_service(
                cast(type, IResilienceCoordinator)
            )
            eos_adapter = _create_eos_adapter(provider)

            # Get cancellation coordinator (optional, registered in streaming phase)
            from src.core.interfaces.session_cancellation_coordinator_interface import (
                ISessionCancellationCoordinator,
            )

            cancellation_coordinator = provider.get_service(
                cast(type, ISessionCancellationCoordinator)
            )

            # Get non-forwardable enforcer (optional, registered in core services stage)
            from src.core.interfaces.non_forwardable_interface import (
                INonForwardableMessageEnforcer,
            )

            non_forwardable_enforcer = provider.get_service(
                cast(type, INonForwardableMessageEnforcer)
            )

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
                connector_invoker=connector_invoker,
                resilience_coordinator=resilience_coordinator,
                eos_adapter=eos_adapter,
                cancellation_coordinator=cancellation_coordinator,
                non_forwardable_enforcer=non_forwardable_enforcer,
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
            logger.warning(
                "Could not register BackendCompletionFlow wiring: %s",
                e,
                exc_info=True,
            )
