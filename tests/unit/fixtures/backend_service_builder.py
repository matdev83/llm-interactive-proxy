"""Test fixtures and builders for BackendService.

This module provides helpers for constructing BackendService in tests
after Phase 4 refactoring removed runtime fallback instantiation.
"""

from typing import Any
from unittest.mock import MagicMock, Mock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.backend_service_interface import IBackendService

from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
)


def create_backend_service_with_di(
    app_config: AppConfig | None = None,
    **overrides: Any,
) -> IBackendService:
    """Create BackendService using DI container (recommended approach).

    This is the cleanest way to construct BackendService in tests, as it
    ensures all dependencies are properly wired just like in production.

    Args:
        app_config: Optional custom AppConfig (uses default if None)
        **overrides: Optional service overrides (e.g., wire_capture=mock_capture)

    Returns:
        Fully-wired IBackendService instance

    Example:
        >>> service = create_backend_service_with_di()
        >>> # Or with custom config:
        >>> config = AppConfig()
        >>> config.backends.default_backend = "openai"
        >>> service = create_backend_service_with_di(app_config=config)
    """
    services = ServiceCollection()

    # Register custom config if provided
    if app_config is not None:
        services.add_instance(AppConfig, app_config)

    # Register core services (includes all BackendService dependencies)
    register_core_services(services, app_config)

    # Apply overrides if provided
    for _service_type, instance in overrides.items():
        # This is a simplification; in real usage you'd use proper type resolution
        services.add_instance(type(instance), instance)

    provider = services.build_service_provider()
    return provider.get_required_service(IBackendService)  # type: ignore[type-abstract,return-value]


def create_backend_service_with_mocks(
    factory: Any = None,
    rate_limiter: Any = None,
    config: Any = None,
    session_service: Any = None,
    app_state: Any = None,
    use_real_completion_flow: bool = False,
    **kwargs: Any,
) -> Any:
    """Create BackendService with explicit mocks (for edge cases).

    Use this when you need fine-grained control over mocked dependencies.
    For most tests, prefer create_backend_service_with_di() instead.

    Args:
        factory: BackendFactory (or mock)
        rate_limiter: IRateLimiter (or mock)
        config: IConfig (or mock)
        session_service: ISessionService (or mock)
        app_state: IApplicationState (or mock)
        **kwargs: Other dependencies (will use mocks if not provided)

    Returns:
        BackendService instance with all dependencies provided

    Example:
        >>> mock_factory = MagicMock(spec=BackendFactory)
        >>> service = create_backend_service_with_mocks(factory=mock_factory)
    """
    from src.core.interfaces.application_state_interface import IApplicationState
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
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
    from src.core.interfaces.failover_interface import IFailoverCoordinator
    from src.core.interfaces.failover_planner_interface import IFailoverPlanner
    from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver
    from src.core.interfaces.planning_phase_manager_interface import (
        IPlanningPhaseManager,
    )
    from src.core.interfaces.rate_limiter_interface import IRateLimiter
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
    from src.core.interfaces.usage_tracking_wrapper_interface import (
        IUsageTrackingWrapper,
    )
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_service import BackendService

    # Required dependencies (no fallbacks in Phase 4)
    if factory is None:
        factory = MagicMock(spec=BackendFactory)
    if rate_limiter is None:
        rate_limiter = MagicMock(spec=IRateLimiter)
    if config is None:
        config = MagicMock(spec=IConfig)
    if session_service is None:
        session_service = MagicMock(spec=ISessionService)
    if app_state is None:
        app_state = MagicMock(spec=IApplicationState)

    # Extract required collaborators from kwargs or create mocks
    backend_config_provider = kwargs.get(
        "backend_config_provider", MagicMock(spec=IBackendConfigProvider)
    )
    stream_formatting_service = kwargs.get(
        "stream_formatting_service", MagicMock(spec=IStreamFormattingService)
    )
    usage_tracking_wrapper = kwargs.get(
        "usage_tracking_wrapper", MagicMock(spec=IUsageTrackingWrapper)
    )
    model_alias_resolver = kwargs.get(
        "model_alias_resolver", MagicMock(spec=IModelAliasResolver)
    )
    exception_normalizer = kwargs.get(
        "exception_normalizer", MagicMock(spec=IExceptionNormalizer)
    )
    backend_lifecycle_manager = kwargs.get(
        "backend_lifecycle_manager", MagicMock(spec=IBackendLifecycleManager)
    )
    planning_phase_manager = kwargs.get(
        "planning_phase_manager", MagicMock(spec=IPlanningPhaseManager)
    )
    reasoning_config_applicator = kwargs.get(
        "reasoning_config_applicator", MagicMock(spec=IReasoningConfigApplicator)
    )
    uri_parameter_applicator = kwargs.get(
        "uri_parameter_applicator", MagicMock(spec=IURIParameterApplicator)
    )
    stream_session_id_resolver = kwargs.get(
        "stream_session_id_resolver", MagicMock(spec=IStreamSessionIdResolver)
    )
    backend_model_resolver = kwargs.get(
        "backend_model_resolver", MagicMock(spec=IBackendModelResolver)
    )

    # Optional dependencies (can be None)
    failover_routes = kwargs.get("failover_routes", None)
    failover_strategy = kwargs.get("failover_strategy", None)
    failover_coordinator = kwargs.get("failover_coordinator", None)
    wire_capture = kwargs.get("wire_capture", None)
    routing_service = kwargs.get("routing_service", None)
    resilience_coordinator = kwargs.get("resilience_coordinator", None)
    failure_handling_strategy = kwargs.get("failure_handling_strategy", None)
    usage_tracking_service = kwargs.get("usage_tracking_service", None)

    # Create real failover planner if coordinator is provided, otherwise use mock
    failover_planner = kwargs.get("failover_planner", None)
    if failover_planner is None and failover_coordinator is not None:
        from src.core.services.failover_planner import FailoverPlanner

        failover_planner = FailoverPlanner(
            app_state=app_state,
            failover_coordinator=failover_coordinator,
            backend_lifecycle_manager=backend_lifecycle_manager,
            config=config,
            failover_strategy=failover_strategy,
            resilience_coordinator=resilience_coordinator,
        )
    elif failover_planner is None:
        failover_planner = MagicMock(spec=IFailoverPlanner)

    backend_completion_flow = kwargs.get("backend_completion_flow", None)
    if backend_completion_flow is None:
        if use_real_completion_flow:
            if failover_coordinator is None:
                failover_coordinator = MagicMock(spec=IFailoverCoordinator)

            # Use real StreamFormattingService when using real completion flow
            # (unless explicitly provided)
            if isinstance(stream_formatting_service, MagicMock):
                from src.core.services.stream_formatting_service import (
                    StreamFormattingService,
                )

                stream_formatting_service = StreamFormattingService()

            if hasattr(backend_model_resolver, "synchronize_request_with_target"):
                method = backend_model_resolver.synchronize_request_with_target
                if isinstance(method, Mock):
                    method.side_effect = lambda request, _resolved: request

            if hasattr(backend_lifecycle_manager, "get_disabled_backends"):
                method = backend_lifecycle_manager.get_disabled_backends
                if isinstance(method, Mock):
                    method.return_value = {}

            # Construct dependencies dict for the helper
            deps = {
                "backend_model_resolver": backend_model_resolver,
                "stream_session_id_resolver": stream_session_id_resolver,
                "failover_planner": failover_planner,
                "session_service": session_service,
                "backend_lifecycle_manager": backend_lifecycle_manager,
                "backend_config_service": backend_config_provider,
                "reasoning_config_applicator": reasoning_config_applicator,
                "uri_parameter_applicator": uri_parameter_applicator,
                "stream_formatting_service": stream_formatting_service,
                "usage_tracking_wrapper": usage_tracking_wrapper,
                "exception_normalizer": exception_normalizer,
                "planning_phase_manager": planning_phase_manager,
                "backend_factory": factory,
                "config": config,
                "app_state": app_state,
                "failover_coordinator": failover_coordinator,
                "wire_capture": wire_capture,
                "usage_tracking_service": usage_tracking_service,
                "resilience_coordinator": resilience_coordinator,
                "failure_handling_strategy": failure_handling_strategy,
                "routing_service": routing_service,
                "failover_routes": failover_routes,
            }
            # Add overrides from kwargs
            deps.update(kwargs)

            backend_completion_flow = create_test_backend_completion_flow(deps)
        else:
            backend_completion_flow = MagicMock(spec=IBackendCompletionFlow)

    return BackendService(
        factory,
        rate_limiter,
        config,
        session_service,
        app_state,
        backend_config_provider,
        stream_formatting_service,
        usage_tracking_wrapper,
        model_alias_resolver,
        exception_normalizer,
        backend_lifecycle_manager,
        planning_phase_manager,
        reasoning_config_applicator,
        uri_parameter_applicator,
        stream_session_id_resolver,
        backend_model_resolver,
        failover_planner,
        backend_completion_flow,
        failover_routes=failover_routes,
        failover_strategy=failover_strategy,
        failover_coordinator=failover_coordinator,
        wire_capture=wire_capture,
        routing_service=routing_service,
        resilience_coordinator=resilience_coordinator,
        failure_handling_strategy=failure_handling_strategy,
        usage_tracking_service=usage_tracking_service,
    )
