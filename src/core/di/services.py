"""
Services and DI container configuration.

This module provides functions for configuring the DI container with services
and resolving services from the container.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar, cast

from src.core.common.exceptions import ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.database.repositories.memory_repository import SQLModelMemoryRepository
from src.core.database.repositories.sso_repository import (
    SQLModelAuthorizationRepository,
    SQLModelRateLimitRepository,
    SQLModelTokenRepository,
)
from src.core.database.repositories.usage_repository import (
    SessionMetricsRepository,
    UsageRecordRepository,
)
from src.core.di.container import ServiceCollection
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
)
from src.core.domain.streaming_response_processor import (
    LoopDetectionProcessor as DomainLoopDetectionProcessor,
)
from src.core.interfaces.agent_response_formatter_interface import (
    IAgentResponseFormatter,
)
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import (
    IBackendRequestManager,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.failure_strategy_interface import (
    FailureHandlingConfig,
    IFailureHandlingStrategy,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver

# Note: IMiddlewareApplicationManager interface is no longer used after unified pipeline refactoring
# MiddlewareApplicationManager is still used to configure the middleware list for streaming processors
from src.core.interfaces.path_validator_interface import IPathValidator
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
)
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.memory.analysis_worker import AnalysisWorker
from src.core.memory.capture_middleware import MemoryCaptureMiddleware
from src.core.memory.completion_detector import SessionCompletionDetector
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.injection_middleware import ContextInjectionMiddleware
from src.core.memory.maintenance import DatabaseMaintenance
from src.core.memory.prompt_loader import PromptLoader
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService
from src.core.memory.sqlite_repository import MemoryRepository
from src.core.memory.summary_generator import SummaryGenerator
from src.core.ports.streaming_processors import (
    ThinkTagsProcessor,
)
from src.core.services.angel_service import AngelService
from src.core.services.app_settings_service import AppSettings
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.backend_config_provider import BackendConfigProvider
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_registry import BackendRegistry
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.backend_service import BackendService
from src.core.services.command_processor import CommandProcessor
from src.core.services.dangerous_command_service import DangerousCommandService
from src.core.services.exception_normalizer import ExceptionNormalizer
from src.core.services.failover_service import FailoverService
from src.core.services.file_sandboxing_handler import FileSandboxingHandler
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)
from src.core.services.model_alias_resolver import ModelAliasResolver
from src.core.services.model_replacement_service import ModelReplacementService
from src.core.services.path_validation_service import PathValidationService
from src.core.services.planning_phase_manager import PlanningPhaseManager
from src.core.services.pytest_compression_service import PytestCompressionService
from src.core.services.reasoning_config_applicator import ReasoningConfigApplicator
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.resilience import RateLimitStateManager, ResilienceCoordinator
from src.core.services.resilience.handlers import (
    AuthErrorHandler,
    RateLimitErrorHandler,
)
from src.core.services.response_handlers import (
    DefaultNonStreamingResponseHandler,
    DefaultStreamingResponseHandler,
)
from src.core.services.response_manager_service import (
    AgentResponseFormatter,
    ResponseManager,
)
from src.core.services.response_parser_service import ResponseParser
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.secure_command_factory import SecureCommandFactory
from src.core.services.secure_state_service import SecureStateService
from src.core.services.session_manager_service import SessionManager
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.services.session_service_impl import SessionService
from src.core.services.stream_formatting_service import StreamFormattingService
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    set_global_streaming_context_registry,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.streaming.vtc_postprocessor import VTCPostProcessor
from src.core.services.streaming.vtc_preprocessor import VTCPreProcessor
from src.core.services.structured_output_middleware import StructuredOutputMiddleware
from src.core.services.tool_call_reactor_service import (
    InMemoryToolCallHistoryTracker,
    ToolCallReactorService,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.core.services.translation_service import TranslationService
from src.core.services.unified_tool_security_handler import UnifiedToolSecurityHandler
from src.core.services.uri_parameter_applicator import URIParameterApplicator
from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper
from src.tool_call_loop.lifecycle_registry import ToolCallLifecycleRegistry

T = TypeVar("T")

# Global service collection
_service_collection: ServiceCollection | None = None
_service_provider: IServiceProvider | None = None


def _get_di_diagnostics() -> bool:
    """Get DI diagnostics setting from environment."""
    return os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def get_service_collection() -> ServiceCollection:
    """Get the global service collection.

    Returns:
        The global service collection
    """
    global _service_collection
    if _service_collection is None:
        _service_collection = ServiceCollection()
        # Ensure core services are registered into the global collection early.
        # This makes DI shape consistent across processes/tests and avoids many
        # order-dependent failures. register_core_services is idempotent.
        try:
            register_core_services(_service_collection, None)
        except Exception as exc:
            logger_for_this_file = logging.getLogger(__name__)
            if logger_for_this_file.isEnabledFor(logging.ERROR):
                logger_for_this_file.error(
                    "Failed to register core services into global service collection",
                    exc_info=True,
                )
            _service_collection = None
            raise ServiceResolutionError(
                "Failed to register core services",
                details={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            ) from exc
    return _service_collection


def get_or_build_service_provider() -> IServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    Returns:
        The global service provider
    """
    global _service_provider
    if _service_provider is None:
        if _get_di_diagnostics():
            di_logger = logging.getLogger("llm.di")
            if di_logger.isEnabledFor(logging.INFO):
                di_logger.info(
                    "Building service provider; descriptors=%d",
                    len(get_service_collection()._descriptors),
                )
        _service_provider = get_service_collection().build_service_provider()
        # Register feature parity tracking after provider is built
        _initialize_feature_parity_registry(_service_provider)
    return _service_provider


def _initialize_feature_parity_registry(provider: IServiceProvider) -> None:
    """Initialize feature parity registry with all registered middleware.

    This registers all middleware and features with the parity registry
    for tracking streaming/non-streaming support.
    """
    try:
        from src.core.interfaces.feature_parity import get_global_registry
        from src.core.interfaces.response_processor_interface import FeatureCapability

        registry = get_global_registry()

        # Register core features (IResponseFeature implementations)
        try:
            from src.core.services.response_middleware import (
                ContentFilterFeature,
                ResponseLoggingFeature,
            )

            registry.register_feature(ResponseLoggingFeature())
            registry.register_feature(ContentFilterFeature())
        except ImportError:
            pass

        try:
            from src.core.services.empty_response_middleware import EmptyResponseFeature

            registry.register_feature(EmptyResponseFeature())
        except ImportError:
            pass

        # Register LoopDetectionFeature with the ILoopDetector from DI
        try:
            from typing import cast

            from src.core.interfaces.loop_detector_interface import ILoopDetector
            from src.core.services.response_middleware import LoopDetectionFeature

            loop_detector = provider.get_service(cast(type, ILoopDetector))
            if loop_detector is not None:
                registry.register_feature(LoopDetectionFeature(loop_detector))
        except Exception:
            pass  # LoopDetector may not be available

        # Register middleware instances from the middleware manager
        try:
            from src.core.interfaces.response_processor_interface import (
                IResponseFeature,
                IResponseMiddleware,
            )

            manager = provider.get_required_service(MiddlewareApplicationManager)
            for mw in manager._middleware:
                if isinstance(mw, IResponseFeature):
                    registry.register_feature(mw)
                elif isinstance(mw, IResponseMiddleware):
                    mw_name = type(mw).__name__
                    # All updated middleware now support both paths
                    registry.register_middleware(
                        mw,
                        declared_capability=FeatureCapability.BOTH,
                        name=mw_name,
                    )
        except Exception:
            pass  # Middleware manager may not be available yet

        parity_logger = logging.getLogger("llm.feature_parity")
        if parity_logger.isEnabledFor(logging.DEBUG):
            parity_logger.debug(
                "Feature parity registry initialized with %d features",
                len(registry.get_all_features()),
            )
    except Exception as e:
        # Don't fail startup due to parity registration issues
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Feature parity initialization skipped: %s", e)


def set_service_provider(provider: IServiceProvider) -> None:
    """Set the global service provider (used for tests/late init).

    Args:
        provider: The ServiceProvider instance to set as the global provider
    """
    global _service_provider
    _service_provider = provider


def get_service_provider() -> IServiceProvider:
    """Return the global service provider, building it if necessary.

    This is a compatibility wrapper used by callers that expect a
    `get_service_provider` symbol.
    """
    provider = get_or_build_service_provider()
    return _ensure_tool_call_reactor_services(provider)


def _ensure_tool_call_reactor_services(
    provider: IServiceProvider,
) -> IServiceProvider:
    """Ensure the provider can resolve ToolCallReactor components.

    Args:
        provider: The current service provider instance.

    Returns:
        A provider that can resolve the ToolCallReactor service and feature.

    Raises:
        ServiceResolutionError: If re-registration fails to provide the required services.
    """

    from src.core.services.tool_call_reactor_middleware import ToolCallReactorFeature
    from src.core.services.tool_call_reactor_service import ToolCallReactorService

    missing_components: list[str] = []

    if provider.get_service(ToolCallReactorService) is None:
        missing_components.append("ToolCallReactorService")
    if provider.get_service(ToolCallReactorFeature) is None:
        # Check if MiddlewareApplicationManager, which contains ToolCallReactorFeature, is available
        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )

        manager = provider.get_service(MiddlewareApplicationManager)
        if manager is None or not any(
            isinstance(f, ToolCallReactorFeature) for f in manager._middleware
        ):
            missing_components.append(
                "ToolCallReactorFeature (not found in MiddlewareApplicationManager)"
            )

    if not missing_components:
        return provider

    logger = logging.getLogger(__name__)
    if logger.isEnabledFor(logging.WARNING):
        logger.warning(
            "DI provider missing tool call reactor components: %s. Re-registering core services.",
            ", ".join(missing_components),
        )

    services = get_service_collection()
    descriptors = getattr(services, "_descriptors", {})

    preserved_descriptors: dict[type, Any] = {}
    for key in (AppConfig, cast(type, IConfig)):
        descriptor = descriptors.get(key)
        if descriptor is not None:
            preserved_descriptors[key] = descriptor

    register_core_services(services)

    descriptors.update(preserved_descriptors)

    new_provider = services.build_service_provider()
    set_service_provider(new_provider)

    still_missing: list[str] = []
    if new_provider.get_service(ToolCallReactorService) is None:
        still_missing.append("ToolCallReactorService")
    if new_provider.get_service(ToolCallReactorFeature) is None:
        # Final check if the feature is available through the manager after re-registration
        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )

        manager = new_provider.get_service(MiddlewareApplicationManager)
        if manager is None or not any(
            isinstance(f, ToolCallReactorFeature) for f in manager._middleware
        ):
            still_missing.append(
                "ToolCallReactorFeature (not found in MiddlewareApplicationManager)"
            )

    if still_missing:
        raise ServiceResolutionError(
            "Failed to register required Tool Call Reactor services.",
            details={"missing_components": still_missing},
        )

    return new_provider


def _resolve_failure_strategy(
    provider: IServiceProvider,
    config: IConfig,
    routing_service: Any = None,
) -> Any:
    """Resolve failure handling strategy from DI or construct from config.

    This helper encapsulates the conditional logic previously in BackendService.__init__
    (lines 141-188), moving config parsing to DI composition root as per Phase 4B.

    Args:
        provider: DI service provider
        config: Application configuration
        routing_service: Optional routing service for backend discovery

    Returns:
        IFailureHandlingStrategy instance or None if disabled
    """
    # Try to get pre-registered strategy from DI first
    from typing import cast

    from src.core.interfaces.failure_strategy_interface import IFailureHandlingStrategy

    failure_handling_strategy = provider.get_service(
        cast(type, IFailureHandlingStrategy)
    )
    if failure_handling_strategy is not None:
        return failure_handling_strategy

    # No pre-registered strategy; check config to determine if we should construct one
    failure_handling_settings = getattr(config, "failure_handling", None)
    if failure_handling_settings is None:
        # Config doesn't have failure_handling section
        return None

    enabled_setting = getattr(failure_handling_settings, "enabled", None)
    if not isinstance(enabled_setting, bool):
        # Invalid or missing enabled setting
        return None

    if not enabled_setting:
        # Explicitly disabled
        return None

    # Construct strategy from config
    from src.core.interfaces.failure_strategy_interface import FailureHandlingConfig
    from src.core.services.failure_handling_strategy import (
        DefaultFailureHandlingStrategy,
    )

    def _coerce_float(name: str, default: float) -> float:
        value = getattr(failure_handling_settings, name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_int(name: str, default: int) -> int:
        value = getattr(failure_handling_settings, name, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return DefaultFailureHandlingStrategy(
        config=FailureHandlingConfig(
            max_silent_wait=_coerce_float("max_silent_wait", 60.0),
            total_timeout_budget=_coerce_float("total_timeout_budget", 90.0),
            keepalive_interval=_coerce_float("keepalive_interval", 8.0),
            max_failover_hops=_coerce_int("max_failover_hops", 5),
            min_retry_wait=_coerce_float("min_retry_wait", 1.0),
        ),
        backend_discovery=routing_service,
    )


def register_core_services(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register core services with the service collection.

    Args:
        services: The service collection to register services with
        app_config: Optional application configuration
    """
    logger: logging.Logger = logging.getLogger(__name__)
    # Register AppConfig and IConfig
    if app_config is not None:
        services.add_instance(AppConfig, app_config)
        # Also register it as IConfig for interface resolution
        try:
            services.add_instance(
                cast(type, IConfig),
                app_config,
            )  # type: ignore[type-abstract]
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to register IConfig interface: {e}")
            # Continue without interface registration if it fails
    else:
        # Register default AppConfig as IConfig for testing and basic functionality
        default_config = AppConfig()
        services.add_instance(AppConfig, default_config)
        try:
            services.add_instance(
                cast(type, IConfig),
                default_config,
            )  # type: ignore[type-abstract]
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to register default IConfig interface: {e}")
            # Continue without interface registration if it fails

    # Helper wrappers to make registration idempotent and provide debug logging

    def _registered(service_type: type) -> bool:
        desc = getattr(services, "_descriptors", None)
        return desc is not None and service_type in desc

    def _add_singleton(
        service_type: type,
        implementation_type: type | None = None,
        implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    ) -> None:
        if _registered(service_type):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping registration of %s; already present",
                    getattr(service_type, "__name__", str(service_type)),
                )
            return
        services.add_singleton(
            service_type, implementation_type, implementation_factory
        )

    def _add_instance(service_type: type, instance: Any) -> None:
        if _registered(service_type):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping instance registration of %s; already present",
                    getattr(service_type, "__name__", str(service_type)),
                )
            return
        services.add_instance(service_type, instance)

    # Register session resolver
    _add_singleton(DefaultSessionResolver)
    # Register both the concrete type and the interface
    _add_singleton(ISessionResolver, DefaultSessionResolver)  # type: ignore[type-abstract]

    # Register CommandService with factory
    def _command_service_factory(provider: IServiceProvider) -> ICommandService:
        from src.core.commands.parser import CommandParser
        from src.core.commands.service import NewCommandService
        from src.core.services.command_policy_service import CommandPolicyService
        from src.core.services.command_state_service import CommandStateService
        from src.core.services.session_service_impl import SessionService

        session_service = provider.get_required_service(SessionService)
        command_parser = provider.get_required_service(CommandParser)
        config = provider.get_required_service(AppConfig)
        app_state = provider.get_service(cast(type, IApplicationState))
        state_service = provider.get_required_service(CommandStateService)
        policy_service = provider.get_required_service(CommandPolicyService)
        return NewCommandService(
            session_service,
            command_parser,
            strict_command_detection=config.strict_command_detection,
            app_state=app_state,
            command_state_service=state_service,
            command_policy_service=policy_service,
            config=config,
        )

    # Register CommandService and bind to interface
    _add_singleton(ICommandService, implementation_factory=_command_service_factory)  # type: ignore[type-abstract]

    # Register CommandParser
    from src.core.commands.parser import CommandParser
    from src.core.interfaces.command_parser_interface import ICommandParser

    _add_singleton(ICommandParser, CommandParser)  # type: ignore[type-abstract]
    _add_singleton(CommandParser, CommandParser)  # Also register concrete type

    # Ensure command handlers are imported so their @command decorators register them
    try:
        import importlib
        import pkgutil

        package_name = "src.core.commands.handlers"
        package = importlib.import_module(package_name)
        for m in pkgutil.iter_modules(package.__path__):  # type: ignore[attr-defined]
            importlib.import_module(f"{package_name}.{m.name}")
    except Exception:
        file_logger = logging.getLogger(__name__)
        if file_logger.isEnabledFor(logging.WARNING):
            file_logger.warning(
                "Failed to import command handlers for registration", exc_info=True
            )

    # Register session service factory
    def _session_service_factory(provider: IServiceProvider) -> SessionService:
        # Import here to avoid circular imports
        from src.core.repositories.in_memory_session_repository import (
            InMemorySessionRepository,
        )

        # Create repository
        repository: InMemorySessionRepository = InMemorySessionRepository()

        # Return session service
        return SessionService(repository)

    # Register session service and bind to interface
    _add_singleton(SessionService, implementation_factory=_session_service_factory)

    try:
        services.add_singleton(
            cast(type, ISessionService), implementation_factory=_session_service_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ISessionService interface: {e}")
        # Continue if concrete SessionService is registered

    # Register command state service
    from src.core.interfaces.command_state_service_interface import (
        ICommandStateService,
    )
    from src.core.services.command_state_service import CommandStateService

    def _command_state_service_factory(
        provider: IServiceProvider,
    ) -> CommandStateService:
        session = provider.get_required_service(SessionService)
        return CommandStateService(session)

    _add_singleton(
        CommandStateService, implementation_factory=_command_state_service_factory
    )

    try:
        services.add_singleton(
            cast(type, ICommandStateService),
            implementation_factory=lambda provider: provider.get_required_service(
                CommandStateService
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandStateService interface: {e}")
        # Continue if concrete CommandStateService is registered

    # Register command policy service
    from src.core.interfaces.command_policy_service_interface import (
        ICommandPolicyService,
    )
    from src.core.services.command_policy_service import CommandPolicyService

    def _command_policy_service_factory(
        provider: IServiceProvider,
    ) -> CommandPolicyService:
        cfg = provider.get_required_service(AppConfig)
        app_state = provider.get_service(cast(type, IApplicationState))
        return CommandPolicyService(cfg, app_state)

    _add_singleton(
        CommandPolicyService, implementation_factory=_command_policy_service_factory
    )

    try:
        services.add_singleton(
            cast(type, ICommandPolicyService),
            implementation_factory=lambda provider: provider.get_required_service(
                CommandPolicyService
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandPolicyService interface: {e}")
        # Continue if concrete CommandPolicyService is registered

    # Register command processor
    def _command_processor_factory(provider: IServiceProvider) -> ICommandProcessor:
        # Get command service
        from typing import cast

        from src.core.commands.tool_call_command_processor import (
            ToolCallCommandProcessor,
        )
        from src.core.services.delegating_command_processor import (
            DelegatingCommandProcessor,
        )

        command_service: ICommandService = provider.get_required_service(
            cast(type, ICommandService)
        )

        # Create the processors
        text_command_processor = CommandProcessor(command_service)
        tool_call_command_processor = ToolCallCommandProcessor(command_service)

        # Return the delegating processor
        return DelegatingCommandProcessor(
            tool_call_command_processor=tool_call_command_processor,
            text_command_processor=text_command_processor,
        )

    # Register command processor and bind to interface
    try:
        services.add_singleton(
            cast(type, ICommandProcessor),
            implementation_factory=_command_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandProcessor interface: {e}")
        # Continue without interface registration if it fails

    # Register backend processor
    def _backend_processor_factory(provider: IServiceProvider) -> BackendProcessor:
        # Get backend service and session service
        from typing import cast

        backend_service: IBackendService = provider.get_required_service(
            cast(type, IBackendService)
        )
        session_service: ISessionService = provider.get_required_service(
            cast(type, ISessionService)
        )
        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)
        )

        # Return backend processor
        return BackendProcessor(backend_service, session_service, app_state)

    # Register backend processor and bind to interface
    _add_singleton(BackendProcessor, implementation_factory=_backend_processor_factory)

    try:
        services.add_singleton(
            cast(type, IBackendProcessor),
            implementation_factory=_backend_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IBackendProcessor interface: {e}")
        # Continue if concrete BackendProcessor is registered

    # Register response handlers
    _add_singleton(DefaultNonStreamingResponseHandler)
    _add_singleton(DefaultStreamingResponseHandler)

    try:
        services.add_singleton(
            cast(type, INonStreamingResponseHandler), DefaultNonStreamingResponseHandler
        )
        services.add_singleton(
            cast(type, IStreamingResponseHandler), DefaultStreamingResponseHandler
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register response handler interfaces: {e}")
        # Continue if concrete handlers are registered

    # Register MiddlewareApplicationManager with configured features (IResponseFeature)
    def _middleware_application_manager_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationManager:
        from src.core.app.middleware.json_repair_middleware import JsonRepairFeature
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.response_processor_interface import (
            IResponseFeature,
            IResponseMiddleware,
        )
        from src.core.services.empty_response_middleware import EmptyResponseFeature
        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )
        from src.core.services.tool_call_loop_middleware import (
            ToolCallLoopDetectionFeature,
        )

        cfg: AppConfig = provider.get_required_service(AppConfig)
        # Use IResponseFeature for enforced streaming/non-streaming parity
        features: list[IResponseFeature | IResponseMiddleware] = []

        try:
            if getattr(cfg.empty_response, "enabled", True):
                features.append(
                    EmptyResponseFeature(
                        enabled=True,
                        max_retries=getattr(cfg.empty_response, "max_retries", 1),
                    )
                )
        except Exception as e:
            file_logger = logging.getLogger(__name__)
            if file_logger.isEnabledFor(logging.WARNING):
                file_logger.warning(
                    "Error configuring EmptyResponseFeature: %s", e, exc_info=True
                )

        # Edit-precision response-side detection (optional)
        try:
            from src.core.services.edit_precision_response_middleware import (
                EditPrecisionFeature,
            )

            app_state = provider.get_required_service(ApplicationStateService)
            features.append(EditPrecisionFeature(app_state))
        except Exception as e:
            file_logger = logging.getLogger(__name__)
            if file_logger.isEnabledFor(logging.WARNING):
                file_logger.warning(
                    "Error configuring EditPrecisionFeature: %s",
                    e,
                    exc_info=True,
                )

        # Think tags fix feature (optional)
        try:
            if getattr(cfg.session, "fix_think_tags_enabled", False):
                from src.core.services.think_tags_fix_middleware import (
                    ThinkTagsFixFeature,
                )

                buffer_size = getattr(
                    cfg.session, "fix_think_tags_streaming_buffer_size", 4096
                )
                features.append(
                    ThinkTagsFixFeature(enabled=True, streaming_buffer_size=buffer_size)
                )
        except Exception as e:
            file_logger = logging.getLogger(__name__)
            if file_logger.isEnabledFor(logging.WARNING):
                file_logger.warning(
                    "Error configuring ThinkTagsFixFeature: %s",
                    e,
                    exc_info=True,
                )

        if getattr(cfg.session, "json_repair_enabled", False):
            json_service: JsonRepairService = provider.get_required_service(
                JsonRepairService
            )
            features.append(JsonRepairFeature(cfg, json_service))

        # Note: ToolCallRepairMiddleware was a pass-through - now handled by
        # ToolCallRepairProcessor in streaming pipeline

        lifecycle_registry = provider.get_required_service(ToolCallLifecycleRegistry)
        features.append(
            ToolCallLoopDetectionFeature(
                lifecycle_registry=lifecycle_registry,
            )
        )

        # Add tool call reactor feature (fail fast if unavailable)
        from src.core.services.tool_call_reactor_middleware import (
            ToolCallReactorFeature,
        )
        from src.core.services.windows_double_ampersand_fixer import (
            WindowsDoubleAmpersandFixer,
        )

        tool_call_reactor = provider.get_required_service(ToolCallReactorService)

        # Create double-ampersand fixer based on configuration
        double_ampersand_enabled = getattr(
            cfg.session, "double_ampersand_fixes_for_windows_enabled", True
        )
        double_ampersand_fixer = WindowsDoubleAmpersandFixer(
            enabled=double_ampersand_enabled
        )

        features.append(
            ToolCallReactorFeature(
                tool_call_reactor=tool_call_reactor,
                lifecycle_registry=lifecycle_registry,
                double_ampersand_fixer=double_ampersand_fixer,
            )
        )

        # Dangerous command prevention handled by Tool Call Reactor handler

        return MiddlewareApplicationManager(features)

    _add_singleton(
        MiddlewareApplicationManager,
        implementation_factory=_middleware_application_manager_factory,
    )
    # Note: IMiddlewareApplicationManager interface registration removed after unified pipeline refactoring
    # The concrete MiddlewareApplicationManager is still used to configure middleware for streaming processors

    # Register MiddlewareApplicationProcessor used inside the streaming pipeline
    def _middleware_application_processor_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationProcessor:
        manager: MiddlewareApplicationManager = provider.get_required_service(
            MiddlewareApplicationManager
        )
        app_state: IApplicationState = provider.get_required_service(
            IApplicationState  # type: ignore[type-abstract]
        )
        registry: StreamingContextRegistry = provider.get_required_service(
            StreamingContextRegistry
        )

        import os

        from src.core.domain.configuration.loop_detection_config import (
            LoopDetectionConfiguration,
        )
        from src.tool_call_loop.config import ToolCallLoopConfig

        env_config = ToolCallLoopConfig.from_env_vars(dict(os.environ))
        loop_config = (
            LoopDetectionConfiguration()
            .with_tool_loop_detection_enabled(env_config.enabled)
            .with_tool_loop_max_repeats(env_config.max_repeats)
            .with_tool_loop_ttl_seconds(env_config.ttl_seconds)
            .with_tool_loop_mode(env_config.mode)
        )

        return MiddlewareApplicationProcessor(
            manager._middleware,
            default_loop_config=loop_config,
            app_state=app_state,
            registry=registry,
        )

    _add_singleton(
        MiddlewareApplicationProcessor,
        implementation_factory=_middleware_application_processor_factory,
    )

    # Register response processor (unified pipeline for both streaming and non-streaming)
    def _response_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        from typing import cast

        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.command_processor_interface import ICommandProcessor
        from src.core.interfaces.model_replacement_service_interface import (
            IModelReplacementService,
        )
        from src.core.interfaces.request_processor_internal import (
            IBackendExecutor,
            IBackendPreparer,
            ICommandHandler,
            IRequestSideEffects,
            IRequestTransformPipeline,
            ISessionEnricher,
        )
        from src.core.interfaces.response_manager_interface import IResponseManager
        from src.core.interfaces.session_manager_interface import ISessionManager

        command_processor: ICommandProcessor = provider.get_required_service(
            cast(type, ICommandProcessor)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        response_manager: IResponseManager = provider.get_required_service(
            cast(type, IResponseManager)
        )
        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)
        )
        replacement_service: IModelReplacementService | None = provider.get_service(
            cast(type, IModelReplacementService)
        )
        session_enricher: ISessionEnricher = provider.get_required_service(
            cast(type, ISessionEnricher)
        )
        request_side_effects: IRequestSideEffects = provider.get_required_service(
            cast(type, IRequestSideEffects)
        )
        command_handler: ICommandHandler = provider.get_required_service(
            cast(type, ICommandHandler)
        )
        backend_preparer: IBackendPreparer = provider.get_required_service(
            cast(type, IBackendPreparer)
        )
        transform_pipeline: IRequestTransformPipeline = provider.get_required_service(
            cast(type, IRequestTransformPipeline)
        )
        backend_executor: IBackendExecutor = provider.get_required_service(
            cast(type, IBackendExecutor)
        )

        return RequestProcessor(
            command_processor=command_processor,
            session_manager=session_manager,
            backend_request_manager=backend_request_manager,
            response_manager=response_manager,
            session_enricher=session_enricher,
            request_side_effects=request_side_effects,
            command_handler=command_handler,
            backend_preparer=backend_preparer,
            transform_pipeline=transform_pipeline,
            backend_executor=backend_executor,
            app_state=app_state,
            replacement_service=replacement_service,
        )

    # Register loop detector and bind to interface
    def _loop_detector_factory(provider: IServiceProvider) -> ILoopDetector:
        config = provider.get_service(AppConfig)
        if (
            config
            and hasattr(config, "session")
            and hasattr(config.session, "loop_detection")
        ):
            loop_config = config.session.loop_detection
            if not loop_config or not loop_config.get("enabled", True):
                # Return NoOpLoopDetector if disabled
                from src.loop_detection.detector import NoOpLoopDetector

                return NoOpLoopDetector()
        # Return active HybridLoopDetector
        from src.loop_detection.config import (
            InternalLoopDetectionConfig,
            PatternThresholds,
        )
        from src.loop_detection.hybrid_detector import HybridLoopDetector

        internal_config = InternalLoopDetectionConfig()
        long_threshold = internal_config.long_pattern_threshold or PatternThresholds(
            min_repetitions=3,
            min_total_length=300,
        )
        short_config = {
            "content_loop_threshold": internal_config.content_loop_threshold,
            "content_chunk_size": internal_config.content_chunk_size,
            "max_history_length": internal_config.max_history_length,
        }
        long_config = {
            "min_pattern_length": long_threshold.min_total_length,
            "max_pattern_length": internal_config.max_pattern_length,
            "min_repetitions": long_threshold.min_repetitions,
            "max_history": internal_config.max_history_length,
        }

        return HybridLoopDetector(
            short_detector_config=short_config,
            long_detector_config=long_config,
        )

    # Register concrete LoopDetector
    from src.loop_detection.hybrid_detector import HybridLoopDetector

    _add_singleton(HybridLoopDetector, implementation_factory=_loop_detector_factory)

    # Register ILoopDetector interface
    try:
        services.add_singleton(
            cast(type, ILoopDetector),
            implementation_factory=_loop_detector_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ILoopDetector interface: {e}")
        # Continue if concrete LoopDetector is registered

    # Register response processor and bind to interface
    _add_singleton(RequestProcessor, implementation_factory=_response_processor_factory)

    try:
        services.add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_response_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IRequestProcessor interface: {e}")
        # Continue if concrete RequestProcessor is registered

    def _application_state_factory(
        provider: IServiceProvider,
    ) -> ApplicationStateService:
        # Create application state service
        return ApplicationStateService()

    # Register app settings
    def _app_settings_factory(provider: IServiceProvider) -> AppSettings:
        # Get app_state from IApplicationState if available
        app_state: Any | None = None
        try:
            app_state_service: IApplicationState | None = provider.get_service(
                ApplicationStateService
            )
            if app_state_service:
                app_state = app_state_service.get_setting("service_provider")
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Could not get app_state from ApplicationStateService: {e}"
                )
            app_state = None

        # Create app settings
        return AppSettings(app_state)

    # Register app settings and bind to interface
    _add_singleton(AppSettings, implementation_factory=_app_settings_factory)

    try:
        services.add_singleton(
            cast(type, IAppSettings), implementation_factory=_app_settings_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IAppSettings interface: {e}")
        # Continue if concrete AppSettings is registered

    # Register application state service
    _add_singleton(ApplicationStateService)

    try:
        services.add_singleton(
            cast(type, IApplicationState),
            implementation_factory=_application_state_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IApplicationState interface: {e}")
        # Continue if concrete ApplicationStateService is registered

    # Register secure state service
    def _secure_state_factory(provider: IServiceProvider) -> SecureStateService:
        app_state = provider.get_required_service(ApplicationStateService)
        return SecureStateService(app_state)

    _add_singleton(SecureStateService, implementation_factory=_secure_state_factory)

    try:
        services.add_singleton(
            cast(type, ISecureStateAccess), implementation_factory=_secure_state_factory
        )  # type: ignore[type-abstract]
        services.add_singleton(
            cast(type, ISecureStateModification),
            implementation_factory=_secure_state_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register secure state interfaces: {e}")
        # Continue if concrete SecureStateService is registered

    # Register secure command factory
    def _secure_command_factory(provider: IServiceProvider) -> SecureCommandFactory:
        secure_state = provider.get_required_service(SecureStateService)
        return SecureCommandFactory(
            state_reader=secure_state, state_modifier=secure_state
        )

    _add_singleton(SecureCommandFactory, implementation_factory=_secure_command_factory)

    # Register conversation fingerprint service
    from src.core.services.conversation_fingerprint_service import (
        ConversationFingerprintService,
    )

    _add_singleton(ConversationFingerprintService)

    # Register history compaction service for context compaction feature
    from src.core.interfaces.history_compaction_interface import (
        IHistoryCompactionService,
    )
    from src.core.services.history_compaction_service import HistoryCompactionService

    _add_singleton(HistoryCompactionService)

    try:
        services.add_singleton(
            cast(type, IHistoryCompactionService),
            implementation_factory=lambda provider: provider.get_required_service(
                HistoryCompactionService
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IHistoryCompactionService interface: {e}"
            )

    # Register session manager
    def _session_manager_factory(provider: IServiceProvider) -> SessionManager:
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        session_resolver = provider.get_required_service(ISessionResolver)  # type: ignore[type-abstract]
        # Get session repository for fingerprint tracking
        session_repository = provider.get_service(cast(type, ISessionRepository))  # type: ignore[type-abstract]
        fingerprint_service = provider.get_required_service(
            ConversationFingerprintService
        )
        return SessionManager(
            session_service,
            session_resolver,
            session_repository=session_repository,
            fingerprint_service=fingerprint_service,
        )

    _add_singleton(SessionManager, implementation_factory=_session_manager_factory)

    try:
        services.add_singleton(
            cast(type, ISessionManager), implementation_factory=_session_manager_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ISessionManager interface: {e}")
        # Continue if concrete SessionManager is registered

    # Register agent response formatter
    def _agent_response_formatter_factory(
        provider: IServiceProvider,
    ) -> AgentResponseFormatter:
        session_service = provider.get_service(SessionService)
        return AgentResponseFormatter(session_service=session_service)

    _add_singleton(
        AgentResponseFormatter, implementation_factory=_agent_response_formatter_factory
    )

    try:
        services.add_singleton(
            cast(type, IAgentResponseFormatter),
            implementation_factory=_agent_response_formatter_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IAgentResponseFormatter interface: {e}")
        # Continue if concrete AgentResponseFormatter is registered

    # Register response manager
    def _response_manager_factory(provider: IServiceProvider) -> ResponseManager:
        agent_response_formatter = provider.get_required_service(IAgentResponseFormatter)  # type: ignore[type-abstract]
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        return ResponseManager(agent_response_formatter, session_service)

    _add_singleton(ResponseManager, implementation_factory=_response_manager_factory)

    try:
        services.add_singleton(
            cast(type, IResponseManager),
            implementation_factory=_response_manager_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IResponseManager interface: {e}")
        # Continue if concrete ResponseManager is registered

    # Register ResponseProcessor
    def _real_response_processor_factory(
        provider: IServiceProvider,
    ) -> ResponseProcessor:
        from src.core.interfaces.response_parser_interface import IResponseParser
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )
        from src.core.memory.capture_middleware import MemoryCaptureMiddleware

        response_parser: IResponseParser = provider.get_required_service(
            cast(type, IResponseParser)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        stream_normalizer = provider.get_service(cast(type, IStreamNormalizer))
        memory_capture = provider.get_service(MemoryCaptureMiddleware)

        return ResponseProcessor(
            response_parser=response_parser,
            app_state=app_state,
            stream_normalizer=stream_normalizer,
            memory_capture=memory_capture,
        )

    _add_singleton(
        ResponseProcessor, implementation_factory=_real_response_processor_factory
    )
    services.add_singleton(
        cast(type, IResponseProcessor),
        implementation_factory=_real_response_processor_factory,
    )

    # Register backend request manager
    def _backend_request_manager_factory(
        provider: IServiceProvider,
    ) -> BackendRequestManager:
        from src.core.services.request_deduplication_service import (
            RequestDeduplicationService,
        )

        backend_processor = provider.get_required_service(IBackendProcessor)  # type: ignore[type-abstract]
        response_processor = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]
        angel_service_factory = provider.get_required_service(IAngelServiceFactory)  # type: ignore[type-abstract]
        wire_capture = provider.get_required_service(IWireCapture)  # type: ignore[type-abstract]
        # Optional: history compaction service for context compaction feature
        history_compaction_service = provider.get_service(HistoryCompactionService)
        config = provider.get_required_service(AppConfig)

        # Request deduplication service (configurable via config.request_dedup_window)
        dedup_window = getattr(config, "request_dedup_window", 3.0)
        dedup_max_cache = getattr(config, "request_dedup_max_cache", 10000)
        dedup_enabled = dedup_window > 0
        dedup_service: RequestDeduplicationService | None = None
        if dedup_enabled:
            dedup_service = RequestDeduplicationService(
                window_seconds=dedup_window,
                enabled=True,
                max_cache_size=dedup_max_cache,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Request deduplication enabled with window=%.1fs, max_cache=%d",
                    dedup_window,
                    dedup_max_cache,
                )

        return BackendRequestManager(
            backend_processor,
            response_processor,
            angel_service_factory,
            wire_capture,
            history_compaction_service=history_compaction_service,
            config=config,
            dedup_service=dedup_service,
        )

    _add_singleton(
        BackendRequestManager, implementation_factory=_backend_request_manager_factory
    )

    try:
        services.add_singleton(
            cast(type, IBackendRequestManager),
            implementation_factory=_backend_request_manager_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IBackendRequestManager interface: {e}")
        # Continue if concrete BackendRequestManager is registered

    # =========================================================================
    # Database Layer Registration (SQLModel)
    # =========================================================================

    # Register database configuration
    def _database_config_factory(
        provider: IServiceProvider,
    ) -> DatabaseConfig:
        cfg = provider.get_required_service(AppConfig)
        return cfg.database

    _add_singleton(DatabaseConfig, implementation_factory=_database_config_factory)

    # Register database engine
    def _database_engine_factory(
        provider: IServiceProvider,
    ) -> DatabaseEngine:
        db_config = provider.get_required_service(DatabaseConfig)
        return DatabaseEngine(db_config)

    _add_singleton(DatabaseEngine, implementation_factory=_database_engine_factory)

    # Register SQLModel memory repository
    def _sqlmodel_memory_repository_factory(
        provider: IServiceProvider,
    ) -> SQLModelMemoryRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return SQLModelMemoryRepository(engine)

    _add_singleton(
        SQLModelMemoryRepository,
        implementation_factory=_sqlmodel_memory_repository_factory,
    )

    # Register SQLModel token repository
    def _sqlmodel_token_repository_factory(
        provider: IServiceProvider,
    ) -> SQLModelTokenRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return SQLModelTokenRepository(engine)

    _add_singleton(
        SQLModelTokenRepository,
        implementation_factory=_sqlmodel_token_repository_factory,
    )

    # Register SQLModel rate limit repository
    def _sqlmodel_rate_limit_repository_factory(
        provider: IServiceProvider,
    ) -> SQLModelRateLimitRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return SQLModelRateLimitRepository(engine)

    _add_singleton(
        SQLModelRateLimitRepository,
        implementation_factory=_sqlmodel_rate_limit_repository_factory,
    )

    # Register SQLModel authorization repository
    def _sqlmodel_authorization_repository_factory(
        provider: IServiceProvider,
    ) -> SQLModelAuthorizationRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return SQLModelAuthorizationRepository(engine)

    _add_singleton(
        SQLModelAuthorizationRepository,
        implementation_factory=_sqlmodel_authorization_repository_factory,
    )

    # Register SQLModel usage record repository
    def _sqlmodel_usage_record_repository_factory(
        provider: IServiceProvider,
    ) -> UsageRecordRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return UsageRecordRepository(engine)

    _add_singleton(
        UsageRecordRepository,
        implementation_factory=_sqlmodel_usage_record_repository_factory,
    )

    # Register SQLModel session metrics repository
    def _sqlmodel_session_metrics_repository_factory(
        provider: IServiceProvider,
    ) -> SessionMetricsRepository:
        engine = provider.get_required_service(DatabaseEngine)
        return SessionMetricsRepository(engine)

    _add_singleton(
        SessionMetricsRepository,
        implementation_factory=_sqlmodel_session_metrics_repository_factory,
    )

    # =========================================================================
    # Memory Layer Registration (Legacy - will be migrated to SQLModel)
    # =========================================================================

    # Register memory configuration
    def _memory_configuration_factory(
        provider: IServiceProvider,
    ) -> MemoryConfiguration:
        cfg = provider.get_required_service(AppConfig)
        return cfg.memory

    _add_singleton(
        MemoryConfiguration, implementation_factory=_memory_configuration_factory
    )

    # Register memory repository - use SQLModel implementation
    # Note: Legacy MemoryRepository is kept for backward compatibility during transition
    # New code should inject IMemoryRepository or SQLModelMemoryRepository

    def _memory_repository_factory(
        provider: IServiceProvider,
    ) -> SQLModelMemoryRepository:
        return provider.get_required_service(SQLModelMemoryRepository)

    # Register IMemoryRepository to use SQLModel implementation
    _add_singleton(
        cast(type, IMemoryRepository),
        implementation_factory=_memory_repository_factory,
    )

    # Legacy registration for code still using concrete MemoryRepository type
    def _legacy_memory_repository_factory(
        provider: IServiceProvider,
    ) -> MemoryRepository:
        cfg = provider.get_required_service(MemoryConfiguration)
        return MemoryRepository(cfg)

    _add_singleton(
        MemoryRepository, implementation_factory=_legacy_memory_repository_factory
    )

    # Register prompt loader
    def _prompt_loader_factory(provider: IServiceProvider) -> PromptLoader:
        cfg = provider.get_required_service(MemoryConfiguration)
        return PromptLoader(
            summary_prompt_path=cfg.summary_prompt,
            context_prompt_path=cfg.context_prompt,
        )

    _add_singleton(PromptLoader, implementation_factory=_prompt_loader_factory)

    # Register summary generator
    def _summary_generator_factory(provider: IServiceProvider) -> SummaryGenerator:
        cfg = provider.get_required_service(MemoryConfiguration)
        repo = provider.get_required_service(SQLModelMemoryRepository)
        loader = provider.get_required_service(PromptLoader)
        return SummaryGenerator(
            config=cfg,
            repository=repo,
            prompt_loader=loader,
        )

    _add_singleton(SummaryGenerator, implementation_factory=_summary_generator_factory)

    # Register context injector
    def _context_injector_factory(provider: IServiceProvider) -> ContextInjector:
        cfg = provider.get_required_service(MemoryConfiguration)
        repo = provider.get_required_service(SQLModelMemoryRepository)
        loader = provider.get_required_service(PromptLoader)
        return ContextInjector(
            config=cfg,
            repository=repo,
            prompt_loader=loader,
        )

    _add_singleton(ContextInjector, implementation_factory=_context_injector_factory)

    # Register memory service
    def _memory_service_factory(provider: IServiceProvider) -> MemoryService:
        cfg = provider.get_required_service(MemoryConfiguration)
        repo = provider.get_required_service(SQLModelMemoryRepository)
        return MemoryService(config=cfg, repository=repo)

    _add_singleton(MemoryService, implementation_factory=_memory_service_factory)
    _add_singleton(
        cast(type, IMemoryService), implementation_factory=_memory_service_factory
    )

    # Register database maintenance
    def _database_maintenance_factory(
        provider: IServiceProvider,
    ) -> DatabaseMaintenance:
        cfg = provider.get_required_service(MemoryConfiguration)
        repo = provider.get_required_service(SQLModelMemoryRepository)
        return DatabaseMaintenance(config=cfg, repository=repo)

    _add_singleton(
        DatabaseMaintenance, implementation_factory=_database_maintenance_factory
    )

    # Register analysis worker
    def _analysis_worker_factory(
        provider: IServiceProvider,
    ) -> AnalysisWorker:
        cfg = provider.get_required_service(MemoryConfiguration)
        memory_service = provider.get_required_service(MemoryService)
        summary_generator = provider.get_required_service(SummaryGenerator)
        return AnalysisWorker(
            memory_service=memory_service,
            summary_generator=summary_generator,
            config=cfg,
        )

    _add_singleton(AnalysisWorker, implementation_factory=_analysis_worker_factory)

    # Register session completion detector
    def _session_completion_detector_factory(
        provider: IServiceProvider,
    ) -> SessionCompletionDetector:
        memory_service = provider.get_required_service(
            MemoryService
        )  # Use concrete type
        cfg = provider.get_required_service(MemoryConfiguration)
        return SessionCompletionDetector(memory_service=memory_service, config=cfg)

    _add_singleton(
        SessionCompletionDetector,
        implementation_factory=_session_completion_detector_factory,
    )

    # Register memory capture middleware
    def _memory_capture_middleware_factory(
        provider: IServiceProvider,
    ) -> MemoryCaptureMiddleware:
        from src.core.interfaces.memory_service_interface import IMemoryService

        memory_service: IMemoryService = provider.get_required_service(
            cast(type, IMemoryService)
        )
        cfg = provider.get_required_service(MemoryConfiguration)
        return MemoryCaptureMiddleware(memory_service=memory_service, config=cfg)

    _add_singleton(
        MemoryCaptureMiddleware,
        implementation_factory=_memory_capture_middleware_factory,
    )

    # Register context injection middleware
    def _context_injection_middleware_factory(
        provider: IServiceProvider,
    ) -> Any:  # Use Any to bypass F821
        from src.core.interfaces.memory_service_interface import IMemoryService
        from src.core.memory.config import MemoryConfiguration
        from src.core.memory.context_injector import ContextInjector
        from src.core.memory.injection_middleware import ContextInjectionMiddleware

        memory_service: IMemoryService = provider.get_required_service(
            cast(type, IMemoryService)
        )  # Use interface type
        context_injector = provider.get_required_service(ContextInjector)
        cfg = provider.get_required_service(MemoryConfiguration)
        return ContextInjectionMiddleware(
            memory_service=memory_service, context_injector=context_injector, config=cfg
        )

    _add_singleton(
        ContextInjectionMiddleware,
        implementation_factory=_context_injection_middleware_factory,
    )

    # Register stream normalizer
    def _stream_normalizer_factory(provider: IServiceProvider) -> StreamNormalizer:
        from src.core.ports.streaming_processors import ThinkTagsProcessor

        # Retrieve all stream processors in the correct order
        try:
            from src.core.config.app_config import AppConfig

            app_config: AppConfig = provider.get_required_service(AppConfig)

            # Optional JSON repair processor (enabled via config)
            json_repair_processor = None
            if getattr(app_config.session, "json_repair_enabled", False):
                json_repair_processor = provider.get_required_service(
                    JsonRepairProcessor
                )
            tool_call_repair_processor = None
            if getattr(app_config.session, "tool_call_repair_enabled", True):
                tool_call_repair_processor = provider.get_required_service(
                    ToolCallRepairProcessor
                )
            loop_detection_processor = None
            try:
                loop_detection_processor = provider.get_required_service(
                    DomainLoopDetectionProcessor
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "LoopDetectionProcessor successfully registered for streaming"
                    )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register LoopDetectionProcessor for streaming: {e}"
                    )
                loop_detection_processor = None
            middleware_application_processor = provider.get_required_service(
                MiddlewareApplicationProcessor
            )
            provider.get_required_service(ContentAccumulationProcessor)

            processors: list[IStreamProcessor] = []
            # Prefer JSON repair first so JSON blocks are valid
            if json_repair_processor is not None:
                processors.append(json_repair_processor)
            # Then text loop detection
            if loop_detection_processor is not None:
                processors.append(loop_detection_processor)

            if app_config.session.fix_think_tags_enabled:
                try:
                    think_tags_processor = provider.get_required_service(
                        ThinkTagsProcessor
                    )
                    processors.append(cast(IStreamProcessor, think_tags_processor))
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "ThinkTagsProcessor successfully registered for streaming"
                        )
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Failed to register ThinkTagsProcessor for streaming: {e}"
                        )
            # Then tool-call repair
            if tool_call_repair_processor is not None:
                processors.append(tool_call_repair_processor)
            # Middleware application
            processors.append(middleware_application_processor)
            # NOTE: ContentAccumulationProcessor is NOT added to streaming pipeline
            # because it buffers all content until done, which breaks streaming.
            # It should only be used for non-streaming responses if needed.
        except Exception as e:
            # Fail fast: streaming pipeline must be fully configured
            # Empty processor list fallback is no longer acceptable (P0-3 fix)
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to create stream processors: {e}. "
                    "Streaming pipeline requires all processors to be properly configured."
                )
            raise ServiceResolutionError(
                "Failed to create streaming pipeline processors",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            ) from e

        return StreamNormalizer(processors)

    _add_singleton(StreamNormalizer, implementation_factory=_stream_normalizer_factory)

    try:
        services.add_singleton(
            cast(type, IStreamNormalizer),
            implementation_factory=_stream_normalizer_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IStreamNormalizer interface: {e}")
        # Continue if concrete StreamNormalizer is registered

    # Register ResponseParser
    def _response_parser_factory(provider: IServiceProvider) -> ResponseParser:

        return ResponseParser()

    _add_singleton(ResponseParser, implementation_factory=_response_parser_factory)
    try:
        services.add_singleton(
            cast(type, IResponseParser), implementation_factory=_response_parser_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IResponseParser interface: {e}")
        # Continue if concrete ResponseParser is registered

    # Register individual stream processors
    def _loop_detection_processor_factory(
        provider: IServiceProvider,
    ) -> DomainLoopDetectionProcessor:
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        # Create a factory function that creates new detector instances
        # This ensures each session gets its own isolated detector
        def create_detector() -> ILoopDetector:
            return provider.get_required_service(cast(type, ILoopDetector))

        return DomainLoopDetectionProcessor(loop_detector_factory=create_detector)

    _add_singleton(
        DomainLoopDetectionProcessor,
        implementation_factory=_loop_detection_processor_factory,
    )

    def _stream_context_registry_factory(
        provider: IServiceProvider,
    ) -> StreamingContextRegistry:
        registry = StreamingContextRegistry()
        set_global_streaming_context_registry(registry)
        return registry

    _add_singleton(
        StreamingContextRegistry,
        implementation_factory=_stream_context_registry_factory,
    )

    def _tool_call_repair_processor_factory(
        provider: IServiceProvider,
    ) -> ToolCallRepairProcessor:
        repair_service = provider.get_required_service(ToolCallRepairService)
        registry = provider.get_required_service(StreamingContextRegistry)
        return ToolCallRepairProcessor(
            tool_call_repair_service=repair_service, registry=registry
        )

    _add_singleton(
        ToolCallRepairProcessor,
        implementation_factory=_tool_call_repair_processor_factory,
    )

    def _ports_tool_call_repair_processor_factory(
        provider: IServiceProvider,
    ) -> IStreamProcessor:
        from src.core.ports.streaming_processors import (
            ToolCallRepairProcessor as PortsToolCallRepairProcessor,
        )

        return PortsToolCallRepairProcessor()

    from src.core.ports.streaming_processors import (
        ToolCallRepairProcessor as PortsToolCallRepairProcessor,
    )

    _add_singleton(
        PortsToolCallRepairProcessor,
        implementation_factory=_ports_tool_call_repair_processor_factory,
    )

    def _think_tags_processor_factory(
        provider: IServiceProvider,
    ) -> IStreamProcessor:
        app_config = provider.get_required_service(AppConfig)
        return cast(
            IStreamProcessor,
            ThinkTagsProcessor(
                enabled=getattr(app_config.session, "fix_think_tags_enabled", True),
                streaming_buffer_size=getattr(
                    app_config.session, "fix_think_tags_streaming_buffer_size", 16384
                ),
            ),
        )

    _add_singleton(
        ThinkTagsProcessor, implementation_factory=_think_tags_processor_factory
    )

    # Register VTC Pre-Processor for Virtual Tool Calling support
    def _vtc_preprocessor_factory(
        provider: IServiceProvider,
    ) -> VTCPreProcessor:
        registry = provider.get_required_service(StreamingContextRegistry)
        return VTCPreProcessor(registry=registry)

    _add_singleton(VTCPreProcessor, implementation_factory=_vtc_preprocessor_factory)

    # Register VTC Post-Processor for Virtual Tool Calling support
    def _vtc_postprocessor_factory(
        provider: IServiceProvider,
    ) -> VTCPostProcessor:
        registry = provider.get_required_service(StreamingContextRegistry)
        return VTCPostProcessor(registry=registry)

    _add_singleton(VTCPostProcessor, implementation_factory=_vtc_postprocessor_factory)

    # Register LoopDetectionProcessor from ports.streaming_processors for streaming integration
    def _ports_loop_detection_processor_factory(
        provider: IServiceProvider,
    ) -> IStreamProcessor:
        from src.core.ports.streaming_processors import (
            LoopDetectionProcessor as PortsLoopDetectionProcessor,
        )

        return PortsLoopDetectionProcessor(
            content_loop_threshold=10,
            content_chunk_size=50,
            max_history_length=1000,
        )

    from src.core.ports.streaming_processors import (
        LoopDetectionProcessor as PortsLoopDetectionProcessor,
    )

    _add_singleton(
        PortsLoopDetectionProcessor,
        implementation_factory=_ports_loop_detection_processor_factory,
    )

    # Register ContentAccumulationProcessor with configured buffer limit
    def _content_accumulation_processor_factory(
        provider: IServiceProvider,
    ) -> ContentAccumulationProcessor:
        from src.core.config.app_config import AppConfig

        config: AppConfig = provider.get_required_service(AppConfig)
        buffer_cap = getattr(
            config.session, "content_accumulation_buffer_cap_bytes", 10 * 1024 * 1024
        )
        registry = provider.get_required_service(StreamingContextRegistry)
        return ContentAccumulationProcessor(
            max_buffer_bytes=buffer_cap, registry=registry
        )

    _add_singleton(
        ContentAccumulationProcessor,
        implementation_factory=_content_accumulation_processor_factory,
    )

    # Register JSON repair service and processor
    def _json_repair_service_factory(provider: IServiceProvider) -> JsonRepairService:
        return JsonRepairService()

    _add_singleton(
        JsonRepairService, implementation_factory=_json_repair_service_factory
    )

    # Register StructuredOutputMiddleware
    def _structured_output_middleware_factory(
        provider: IServiceProvider,
    ) -> StructuredOutputMiddleware:
        json_repair_service: JsonRepairService = provider.get_required_service(
            JsonRepairService
        )
        return StructuredOutputMiddleware(json_repair_service)

    _add_singleton(
        StructuredOutputMiddleware,
        implementation_factory=_structured_output_middleware_factory,
    )

    def _json_repair_processor_factory(
        provider: IServiceProvider,
    ) -> JsonRepairProcessor:
        from src.core.config.app_config import AppConfig

        config: AppConfig = provider.get_required_service(AppConfig)
        service: JsonRepairService = provider.get_required_service(JsonRepairService)
        registry: StreamingContextRegistry = provider.get_required_service(
            StreamingContextRegistry
        )
        return JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=getattr(
                config.session, "json_repair_buffer_cap_bytes", 64 * 1024
            ),
            strict_mode=getattr(config.session, "json_repair_strict_mode", False),
            schema=getattr(config.session, "json_repair_schema", None),
            enabled=getattr(config.session, "json_repair_enabled", False),
            registry=registry,
        )

    _add_singleton(
        JsonRepairProcessor, implementation_factory=_json_repair_processor_factory
    )

    # Wire capture service is registered in CoreServicesStage using BufferedWireCapture.
    # Intentionally avoid legacy StructuredWireCapture registration here to keep
    # the active format consistent across the app.

    # Register tool call repair service (if not already registered elsewhere as a concrete type)
    def _tool_call_repair_service_factory(
        provider: IServiceProvider,
    ) -> ToolCallRepairService:
        return ToolCallRepairService()

    _add_singleton(
        ToolCallRepairService, implementation_factory=_tool_call_repair_service_factory
    )

    # Register AngelServiceFactory
    class _AngelServiceFactory(IAngelServiceFactory):
        def create(self, model_spec: str) -> AngelService:
            return AngelService(model_spec)

    def _angel_service_factory_factory(
        provider: IServiceProvider,
    ) -> IAngelServiceFactory:
        return _AngelServiceFactory()

    _add_singleton(
        IAngelServiceFactory, implementation_factory=_angel_service_factory_factory  # type: ignore[type-abstract]
    )
    # IAngelServiceFactory already registered above via _add_singleton

    # Register TranslationService (dependency of BackendService)
    from src.core.domain.translators.defaults import (
        ensure_default_translator_factories_registered,
    )
    from src.core.domain.translators.registry import (
        TranslatorRegistry,
        get_global_translator_registry,
    )

    def _translator_registry_factory(provider: IServiceProvider) -> TranslatorRegistry:
        registry = get_global_translator_registry()
        ensure_default_translator_factories_registered(registry)
        return registry

    _add_singleton(
        TranslatorRegistry, implementation_factory=_translator_registry_factory
    )

    def _translation_service_factory(provider: IServiceProvider) -> TranslationService:
        return TranslationService(
            translator_registry=provider.get_required_service(TranslatorRegistry)
        )

    _add_singleton(
        TranslationService, implementation_factory=_translation_service_factory
    )

    # Register ITranslationService interface to resolve to the same singleton instance
    def _translation_service_interface_factory(
        provider: IServiceProvider,
    ) -> TranslationService:
        return provider.get_required_service(TranslationService)

    _add_singleton(
        cast(type, ITranslationService),
        implementation_factory=_translation_service_interface_factory,
    )

    # Register memory command handlers
    try:
        from src.core.commands.handlers.memory_command_handlers import (
            MemoryOffCommandHandler,
            MemoryOnCommandHandler,
            MemoryStatusCommandHandler,
        )

        _add_singleton(MemoryOnCommandHandler)
        _add_singleton(MemoryOffCommandHandler)
        _add_singleton(MemoryStatusCommandHandler)
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register memory command handlers: {e}")

    # Register assessment services if enabled
    if app_config and app_config.assessment.enabled:
        logger.info(
            "LLM Assessment System ACTIVATED - Monitoring conversations for unproductive patterns"
        )

        # Initialize assessment prompts first
        from src.core.services.assessment_prompts import initialize_prompts

        try:
            initialize_prompts()
            logger.info("Assessment prompts loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load assessment prompts: {e}")
            raise

        # Import assessment services only when needed to avoid circular imports
        from src.core.interfaces.assessment_service_interface import (
            IAssessmentBackendService,
            IAssessmentRepository,
            IAssessmentService,
            ITurnCounterService,
        )
        from src.core.repositories.assessment_repository import (
            InMemoryAssessmentRepository,
        )
        from src.core.services.assessment_backend_service import (
            AssessmentBackendService,
        )
        from src.core.services.assessment_service import AssessmentService
        from src.core.services.turn_counter_service import TurnCounterService

        # Assessment repository
        def _assessment_repository_factory(
            provider: IServiceProvider,
        ) -> InMemoryAssessmentRepository:
            return InMemoryAssessmentRepository()

        _add_singleton(
            IAssessmentRepository, implementation_factory=_assessment_repository_factory  # type: ignore[type-abstract]
        )

        # Turn counter service
        def _turn_counter_service_factory(
            provider: IServiceProvider,
        ) -> TurnCounterService:
            repository = provider.get_required_service(IAssessmentRepository)  # type: ignore[type-abstract]
            config = provider.get_required_service(AppConfig).assessment
            return TurnCounterService(repository, config)

        _add_singleton(
            ITurnCounterService, implementation_factory=_turn_counter_service_factory  # type: ignore[type-abstract]
        )

        # Assessment backend service

        def _assessment_backend_service_factory(
            provider: IServiceProvider,
        ) -> AssessmentBackendService:
            backend_service = provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
            config = provider.get_required_service(AppConfig).assessment
            return AssessmentBackendService(backend_service, config)

        _add_singleton(
            IAssessmentBackendService,
            implementation_factory=_assessment_backend_service_factory,  # type: ignore[type-abstract]
        )

        # Core assessment service

        def _assessment_service_factory(
            provider: IServiceProvider,
        ) -> AssessmentService:
            backend_service = provider.get_required_service(IAssessmentBackendService)  # type: ignore[type-abstract]
            config = provider.get_required_service(AppConfig).assessment
            return AssessmentService(backend_service, config)

        _add_singleton(
            IAssessmentService, implementation_factory=_assessment_service_factory  # type: ignore[type-abstract]
        )

        logger.info(
            f"Assessment services registered: backend={app_config.assessment.backend}, "
            f"model={app_config.assessment.model}, threshold={app_config.assessment.turn_threshold}"
        )

    try:
        services.add_singleton(
            cast(type, IToolCallRepairService),
            implementation_factory=_tool_call_repair_service_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IToolCallRepairService interface: {e}")
        # Continue if concrete ToolCallRepairService is registered

    # Register dangerous command service
    def _dangerous_command_service_factory(
        provider: IServiceProvider,
    ) -> DangerousCommandService:
        from src.core.config.app_config import AppConfig
        from src.core.domain.configuration.dangerous_command_config import (
            DEFAULT_DANGEROUS_COMMAND_CONFIG,
        )
        from src.core.services.dangerous_command_service import (
            DangerousCommandService,
        )

        provider.get_required_service(AppConfig)
        return DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG)

    _add_singleton(
        DangerousCommandService,
        implementation_factory=_dangerous_command_service_factory,
    )

    # Register pytest compression service
    def _pytest_compression_service_factory(
        provider: IServiceProvider,
    ) -> PytestCompressionService:
        from src.core.services.pytest_compression_service import (
            PytestCompressionService,
        )

        provider.get_required_service(AppConfig)
        return PytestCompressionService()

    _add_singleton(
        PytestCompressionService,
        implementation_factory=_pytest_compression_service_factory,
    )

    # Register tool access policy service
    from src.core.services.tool_access_policy_service import ToolAccessPolicyService

    def _tool_access_policy_service_factory(
        provider: IServiceProvider,
    ) -> ToolAccessPolicyService:
        from src.core.config.app_config import AppConfig

        app_config: AppConfig = provider.get_required_service(AppConfig)
        reactor_config = app_config.session.tool_call_reactor

        # Get global overrides from session config (set by CLI parameters)
        global_overrides = getattr(
            app_config.session, "tool_access_global_overrides", None
        )
        return ToolAccessPolicyService(
            reactor_config, global_overrides=global_overrides
        )

    _add_singleton(
        ToolAccessPolicyService,
        implementation_factory=_tool_access_policy_service_factory,
    )

    # Register tool call reactor services
    def _tool_call_history_tracker_factory(
        provider: IServiceProvider,
    ) -> InMemoryToolCallHistoryTracker:
        return InMemoryToolCallHistoryTracker()

    _add_singleton(
        InMemoryToolCallHistoryTracker,
        implementation_factory=_tool_call_history_tracker_factory,
    )

    def _tool_call_reactor_factory(
        provider: IServiceProvider,
    ) -> ToolCallReactorService:
        from src.core.config.app_config import AppConfig

        history_tracker = provider.get_required_service(InMemoryToolCallHistoryTracker)
        reactor = ToolCallReactorService(history_tracker)

        # Get configuration
        app_config: AppConfig = provider.get_required_service(AppConfig)
        reactor_config = app_config.session.tool_call_reactor

        # Register default handlers if enabled
        if reactor_config.enabled:
            # Register UnifiedSteeringHandler (the only steering implementation)
            # Legacy handlers have been removed - unified steering is always used
            try:
                from src.services.steering import UnifiedSteeringHandler

                # Resolve from DI (registered in SteeringStage)
                unified_handler = provider.get_service(UnifiedSteeringHandler)

                if unified_handler:
                    reactor.register_handler_sync(unified_handler)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("Registered UnifiedSteeringHandler")
                else:
                    # This warning may appear during early validation when stages haven't
                    # executed yet. The UnifiedSteeringHandler will be available after
                    # SteeringStage.execute() runs. Log at DEBUG level to reduce noise.
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "UnifiedSteeringHandler not found in DI during factory creation. "
                            "This is expected during early validation; it will be registered "
                            "when SteeringStage executes."
                        )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register UnifiedSteeringHandler: {e}",
                        exc_info=True,
                    )

            # Register UnifiedToolSecurityHandler (replaces separate DangerousCommandHandler
            # and FileSandboxingHandler with a single, more efficient handler)
            try:
                unified_security_handler = provider.get_required_service(
                    UnifiedToolSecurityHandler
                )
                # Only register if at least one feature is enabled
                if unified_security_handler._config.is_any_feature_enabled():
                    try:
                        reactor.register_handler_sync(unified_security_handler)
                        if logger.isEnabledFor(logging.INFO):
                            features = []
                            if (
                                unified_security_handler._config.dangerous_commands.enabled
                            ):
                                features.append("dangerous_commands")
                            if unified_security_handler._config.file_sandboxing.enabled:
                                features.append("file_sandboxing")
                            logger.info(
                                f"Registered UnifiedToolSecurityHandler with features: "
                                f"{', '.join(features)}"
                            )
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register unified security handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register UnifiedToolSecurityHandler: {e}",
                        exc_info=True,
                    )

            # Register PytestContextSavingHandler if enabled
            try:
                if getattr(reactor_config, "pytest_context_saving_enabled", False):
                    from src.core.services.tool_call_handlers.pytest_context_saving_handler import (
                        PytestContextSavingHandler,
                    )

                    context_saving_handler = PytestContextSavingHandler(enabled=True)
                    try:
                        reactor.register_handler_sync(context_saving_handler)
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register pytest context saving handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register PytestContextSavingHandler: {e}",
                        exc_info=True,
                    )

            # Register PytestCompressionHandler if enabled in session config
            try:
                if getattr(app_config.session, "pytest_compression_enabled", True):
                    from src.core.services.tool_call_handlers.pytest_compression_handler import (
                        PytestCompressionHandler,
                    )

                    pytest_compression_service = provider.get_required_service(
                        PytestCompressionService
                    )
                    session_service = provider.get_required_service(SessionService)
                    pytest_handler = PytestCompressionHandler(
                        pytest_compression_service,
                        session_service,
                        enabled=True,
                    )
                    try:
                        reactor.register_handler_sync(pytest_handler)
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register pytest compression handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register PytestCompressionHandler: {e}",
                        exc_info=True,
                    )

            # Register ToolAccessControlHandler if access policies are configured
            try:
                from src.core.services.tool_access_policy_service import (
                    ToolAccessPolicyService,
                )
                from src.core.services.tool_call_handlers.tool_access_control_handler import (
                    ToolAccessControlHandler,
                )

                # Get the policy service
                policy_service = provider.get_required_service(ToolAccessPolicyService)

                # Only register if there are policies configured
                if policy_service._policies:
                    tool_access_handler = ToolAccessControlHandler(
                        policy_service=policy_service,
                        priority=90,  # After dangerous-command handler (100)
                        reactor_service=reactor,  # Pass reactor for telemetry
                    )
                    try:
                        reactor.register_handler_sync(tool_access_handler)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                f"Registered ToolAccessControlHandler with priority 90 "
                                f"({len(policy_service._policies)} policies loaded)"
                            )
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register tool access control handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register ToolAccessControlHandler: {e}",
                        exc_info=True,
                    )

            # Register TestExecutionReminderHandler if enabled
            try:
                if getattr(app_config, "test_execution_reminder_enabled", False):
                    from src.services.test_execution_reminder.test_execution_reminder_handler import (
                        TestExecutionReminderHandler,
                    )

                    # Get custom message if configured
                    custom_message = getattr(
                        app_config, "test_execution_reminder_message", None
                    )

                    test_execution_handler = TestExecutionReminderHandler(
                        message=custom_message,
                        enabled=True,
                    )
                    try:
                        reactor.register_handler_sync(test_execution_handler)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Registered TestExecutionReminderHandler with priority 90"
                            )
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register test execution reminder handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register TestExecutionReminderHandler: {e}",
                        exc_info=True,
                    )

            # Register DroidPathFixHandler if enabled
            try:
                # Check both session and root config for the flag
                flag_enabled = getattr(
                    app_config.session, "droid_path_fix_enabled", False
                ) or getattr(app_config, "droid_path_fix_enabled", False)
                if flag_enabled:
                    from src.core.services.tool_call_handlers.droid_antigravity_path_fix_handler import (
                        DroidAntigravityPathFixHandler,
                    )

                    path_fix_handler = DroidAntigravityPathFixHandler(enabled=True)
                    try:
                        reactor.register_handler_sync(path_fix_handler)
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Registered DroidPathFixHandler with priority 50"
                            )
                    except Exception as e:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                f"Failed to register droid path fix handler: {e}",
                                exc_info=True,
                            )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failed to register DroidPathFixHandler: {e}",
                        exc_info=True,
                    )

        return reactor

    _add_singleton(
        ToolCallReactorService,
        implementation_factory=_tool_call_reactor_factory,
    )

    def _tool_call_lifecycle_registry_factory(
        provider: IServiceProvider,
    ) -> ToolCallLifecycleRegistry:
        return ToolCallLifecycleRegistry()

    _add_singleton(
        ToolCallLifecycleRegistry,
        implementation_factory=_tool_call_lifecycle_registry_factory,
    )

    # NOTE: ToolCallReactorMiddleware is deprecated but still registered for backward
    # compatibility with tests. Production code should use ToolCallReactorFeature
    # (registered via MiddlewareApplicationManager) for proper streaming/non-streaming parity.
    def _tool_call_reactor_middleware_factory(
        provider: IServiceProvider,
    ) -> ToolCallReactorMiddleware:
        from src.core.config.app_config import AppConfig
        from src.core.services.tool_call_reactor_middleware import (
            ToolCallReactorMiddleware,
        )

        reactor = provider.get_required_service(ToolCallReactorService)

        # Get configuration to determine if middleware should be enabled
        app_config: AppConfig = provider.get_required_service(AppConfig)
        enabled = app_config.session.tool_call_reactor.enabled

        lifecycle = provider.get_required_service(ToolCallLifecycleRegistry)

        return ToolCallReactorMiddleware(
            reactor,
            enabled=enabled,
            priority=-10,
            lifecycle_registry=lifecycle,
        )

    from src.core.services.tool_call_reactor_middleware import (
        ToolCallReactorMiddleware,
    )

    _add_singleton(
        ToolCallReactorMiddleware,
        implementation_factory=_tool_call_reactor_middleware_factory,
    )

    # Register PathValidationService
    def _path_validation_service_factory(
        provider: IServiceProvider,
    ) -> PathValidationService:
        return PathValidationService()

    _add_singleton(
        PathValidationService, implementation_factory=_path_validation_service_factory
    )
    _add_singleton(
        IPathValidator,  # type: ignore[type-abstract]
        implementation_factory=lambda p: p.get_required_service(PathValidationService),
    )

    # Register FileSandboxingHandler
    def _file_sandboxing_handler_factory(
        provider: IServiceProvider,
    ) -> FileSandboxingHandler:
        config = provider.get_required_service(AppConfig)
        path_validator = provider.get_required_service(IPathValidator)  # type: ignore[type-abstract]
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]

        return FileSandboxingHandler(
            config=config.sandboxing,
            path_validator=path_validator,
            session_service=session_service,
        )

    _add_singleton(
        FileSandboxingHandler, implementation_factory=_file_sandboxing_handler_factory
    )

    # Register UnifiedToolSecurityHandler (combines dangerous commands + file sandboxing)
    def _unified_tool_security_handler_factory(
        provider: IServiceProvider,
    ) -> UnifiedToolSecurityHandler:
        from src.core.domain.configuration.unified_security_config import (
            UnifiedSecurityConfig,
        )

        app_config = provider.get_required_service(AppConfig)
        path_validator = provider.get_required_service(IPathValidator)  # type: ignore[type-abstract]
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]

        # Build unified config from existing settings
        unified_config = UnifiedSecurityConfig(
            enabled=True,
            priority=100,
        )

        # Configure dangerous commands from session config
        unified_config.dangerous_commands.enabled = getattr(
            app_config.session, "dangerous_command_prevention_enabled", True
        )

        # Configure file sandboxing from sandboxing config
        unified_config.file_sandboxing.enabled = app_config.sandboxing.enabled
        unified_config.file_sandboxing.strict_mode = app_config.sandboxing.strict_mode
        unified_config.file_sandboxing.allow_parent_access = (
            app_config.sandboxing.allow_parent_access
        )
        unified_config.file_sandboxing.custom_tool_patterns = list(
            app_config.sandboxing.custom_tool_patterns
        )
        unified_config.file_sandboxing.excluded_tools = list(
            app_config.sandboxing.excluded_tools
        )
        unified_config.file_sandboxing.path_parameter_names = list(
            app_config.sandboxing.path_parameter_names
        )

        return UnifiedToolSecurityHandler(
            config=unified_config,
            path_validator=path_validator,
            session_service=session_service,
        )

    _add_singleton(
        UnifiedToolSecurityHandler,
        implementation_factory=_unified_tool_security_handler_factory,
    )

    # Register BackendRoutingService
    def _backend_routing_service_factory(
        provider: IServiceProvider,
    ) -> BackendRoutingService:
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )
        from src.core.services.backend_routing_service import BackendRoutingService

        config_provider = provider.get_required_service(IBackendConfigProvider)  # type: ignore[type-abstract]
        app_config = provider.get_required_service(AppConfig)

        return BackendRoutingService(config_provider, app_config.routing)

    from src.core.services.backend_routing_service import BackendRoutingService

    _add_singleton(
        BackendRoutingService, implementation_factory=_backend_routing_service_factory
    )

    # Register resilience layer components
    def _rate_limit_state_manager_factory(
        provider: IServiceProvider,
    ) -> RateLimitStateManager:
        return RateLimitStateManager()

    _add_singleton(
        RateLimitStateManager, implementation_factory=_rate_limit_state_manager_factory
    )

    def _resilience_coordinator_factory(
        provider: IServiceProvider,
    ) -> ResilienceCoordinator:
        state_manager = provider.get_required_service(RateLimitStateManager)

        # Build error handler chain: RateLimit -> Auth
        auth_handler = AuthErrorHandler(state_manager)
        rate_limit_handler = RateLimitErrorHandler(
            state_manager, next_handler=auth_handler
        )

        return ResilienceCoordinator(
            state_manager=state_manager,
            error_handler_chain=rate_limit_handler,
            default_cooldown=60.0,
        )

    _add_singleton(
        ResilienceCoordinator, implementation_factory=_resilience_coordinator_factory
    )

    # Register failure handling strategy
    def _failure_handling_strategy_factory(
        provider: IServiceProvider,
    ) -> IFailureHandlingStrategy:
        from src.core.services.backend_routing_service import BackendRoutingService
        from src.core.services.failure_handling_strategy import (
            DefaultFailureHandlingStrategy,
        )

        # Get routing service for backend discovery
        routing_service = provider.get_service(BackendRoutingService)

        # Get AppConfig to read failure handling settings
        app_config = provider.get_service(AppConfig)
        if app_config is not None and hasattr(app_config, "failure_handling"):
            fh_config = app_config.failure_handling
            # Check if failure handling is disabled
            if not fh_config.enabled:
                logging.getLogger(__name__).info(
                    "Failure handling strategy is disabled via configuration"
                )
                return None  # type: ignore[return-value]

            config = FailureHandlingConfig(
                max_silent_wait=fh_config.max_silent_wait,
                total_timeout_budget=fh_config.total_timeout_budget,
                keepalive_interval=fh_config.keepalive_interval,
                max_failover_hops=fh_config.max_failover_hops,
                min_retry_wait=fh_config.min_retry_wait,
            )
        else:
            # Fallback to defaults if config not available
            config = FailureHandlingConfig(
                max_silent_wait=60.0,
                total_timeout_budget=90.0,
                keepalive_interval=8.0,
                max_failover_hops=5,
                min_retry_wait=1.0,
            )

        return DefaultFailureHandlingStrategy(
            config=config,
            backend_discovery=routing_service,
        )

    _add_singleton(
        cast(type, IFailureHandlingStrategy),
        implementation_factory=_failure_handling_strategy_factory,
    )

    # Register extracted services for BackendService

    # StreamFormattingService
    _add_singleton(StreamFormattingService)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IStreamFormattingService), StreamFormattingService
        )  # type: ignore[type-abstract]

    # UsageTrackingWrapper
    def _usage_tracking_wrapper_factory(
        provider: IServiceProvider,
    ) -> UsageTrackingWrapper:
        usage_service = provider.get_service(
            IUsageTrackingService  # type: ignore[type-abstract]
        )
        stream_service = provider.get_required_service(
            IStreamFormattingService  # type: ignore[type-abstract]
        )
        return UsageTrackingWrapper(
            usage_tracking_service=usage_service,
            stream_formatting_service=stream_service,
        )

    _add_singleton(
        UsageTrackingWrapper, implementation_factory=_usage_tracking_wrapper_factory
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IUsageTrackingWrapper),
            implementation_factory=_usage_tracking_wrapper_factory,
        )  # type: ignore[type-abstract]

    # ModelAliasResolver
    def _model_alias_resolver_factory(
        provider: IServiceProvider,
    ) -> ModelAliasResolver:
        config = provider.get_required_service(AppConfig)
        return ModelAliasResolver(config=config)

    _add_singleton(
        ModelAliasResolver, implementation_factory=_model_alias_resolver_factory
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IModelAliasResolver),
            implementation_factory=_model_alias_resolver_factory,
        )  # type: ignore[type-abstract]

    # URIParameterApplicator
    def _uri_parameter_applicator_factory(
        provider: IServiceProvider,
    ) -> URIParameterApplicator:
        config = provider.get_required_service(AppConfig)
        return URIParameterApplicator(config=config)

    _add_singleton(
        URIParameterApplicator,
        implementation_factory=_uri_parameter_applicator_factory,
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IURIParameterApplicator),
            implementation_factory=_uri_parameter_applicator_factory,
        )  # type: ignore[type-abstract]

    # ReasoningConfigApplicator
    _add_singleton(ReasoningConfigApplicator)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IReasoningConfigApplicator), ReasoningConfigApplicator
        )  # type: ignore[type-abstract]

    # PlanningPhaseManager
    def _planning_phase_manager_factory(
        provider: IServiceProvider,
    ) -> PlanningPhaseManager:
        session_service = provider.get_required_service(
            ISessionService  # type: ignore[type-abstract]
        )
        return PlanningPhaseManager(session_service=session_service)

    _add_singleton(
        PlanningPhaseManager, implementation_factory=_planning_phase_manager_factory
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IPlanningPhaseManager),
            implementation_factory=_planning_phase_manager_factory,
        )  # type: ignore[type-abstract]

    # BackendConfigProvider
    def _backend_config_provider_factory(
        provider: IServiceProvider,
    ) -> BackendConfigProvider:
        from src.core.services.backend_config_provider import BackendConfigProvider

        config = provider.get_required_service(AppConfig)
        return BackendConfigProvider(config)

    _add_singleton(
        BackendConfigProvider, implementation_factory=_backend_config_provider_factory
    )
    try:
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )

        services.add_singleton(
            cast(type, IBackendConfigProvider),
            implementation_factory=_backend_config_provider_factory,
        )  # type: ignore[type-abstract]
    except Exception:
        pass

    # BackendRegistry
    def _backend_registry_factory(provider: IServiceProvider) -> BackendRegistry:
        from src.core.services.backend_registry import (
            backend_registry as global_registry,
        )

        # Ensure connectors are loaded to populate the registry
        # This triggers the self-registration mechanism in src.connectors
        try:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to import src.connectors: {e}")

        return global_registry

    _add_singleton(BackendRegistry, implementation_factory=_backend_registry_factory)

    # BackendFactory
    def _backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
        import httpx

        from src.core.services.backend_factory import BackendFactory

        # Get or create httpx client
        httpx_client: httpx.AsyncClient | None = provider.get_service(httpx.AsyncClient)
        if httpx_client is None:
            # Create a default client if not registered
            # Configuration matches the one in BackendService for consistency
            try:
                httpx_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except ImportError:
                httpx_client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

        registry = provider.get_required_service(BackendRegistry)
        config = provider.get_required_service(AppConfig)
        translation_service = provider.get_required_service(
            ITranslationService  # type: ignore[type-abstract]
        )

        return BackendFactory(
            httpx_client=httpx_client,
            backend_registry=registry,
            config=config,
            translation_service=translation_service,
        )

    _add_singleton(BackendFactory, implementation_factory=_backend_factory_factory)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendFactory),
            implementation_factory=_backend_factory_factory,
        )  # type: ignore[type-abstract]

    # BackendLifecycleManager
    def _backend_lifecycle_manager_factory(
        provider: IServiceProvider,
    ) -> BackendLifecycleManager:
        from src.core.services.backend_factory import BackendFactory

        factory = provider.get_required_service(BackendFactory)
        config = provider.get_required_service(AppConfig)
        backend_config_provider = provider.get_service(
            IBackendConfigProvider  # type: ignore[type-abstract]
        )

        # Helper to resolve per-session limit (duplicate logic from BackendService for now,
        # or we could make it a static method on BackendService or move to config utils)
        default_limit = 32
        per_session_limit = default_limit
        try:
            if hasattr(config, "session"):
                per_session_limit = getattr(
                    config.session, "max_per_session_backends", default_limit
                )
        except Exception:
            pass

        return BackendLifecycleManager(
            factory=factory,
            config=config,
            backend_config_provider=backend_config_provider,
            per_session_limit=per_session_limit,
        )

    _add_singleton(
        BackendLifecycleManager,
        implementation_factory=_backend_lifecycle_manager_factory,
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendLifecycleManager),
            implementation_factory=_backend_lifecycle_manager_factory,
        )  # type: ignore[type-abstract]

    # ExceptionNormalizer
    _add_singleton(ExceptionNormalizer)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IExceptionNormalizer), ExceptionNormalizer
        )  # type: ignore[type-abstract]

    # Register backend service
    def _backend_service_factory(provider: IServiceProvider) -> BackendService:
        # Import required modules
        import httpx

        from src.core.services.backend_factory import BackendFactory
        from src.core.services.rate_limiter import RateLimiter

        # Get or create dependencies
        httpx_client: httpx.AsyncClient | None = provider.get_service(httpx.AsyncClient)
        if httpx_client is None:
            try:
                httpx_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except ImportError:
                httpx_client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

        # Get app config
        app_config: AppConfig = provider.get_required_service(AppConfig)

        backend_factory: BackendFactory = provider.get_required_service(BackendFactory)

        # Resolve the rate limiter from the DI container when available
        rate_limiter: IRateLimiter | None = provider.get_service(RateLimiter)
        if rate_limiter is None:
            rate_limiter = provider.get_service(cast(type, IRateLimiter))
        if rate_limiter is None:
            logging.getLogger(__name__).warning(
                "RateLimiter service not registered; creating transient instance"
            )
            rate_limiter = RateLimiter()

        # Get application state service
        app_state: IApplicationState = provider.get_required_service(
            IApplicationState  # type: ignore[type-abstract]
        )

        # Get failover coordinator (optional for test environments)
        failover_coordinator = None
        try:
            failover_coordinator = provider.get_service(
                IFailoverCoordinator  # type: ignore[type-abstract]
            )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"FailoverCoordinator not available: {e}")

        # Get backend config provider or create one
        backend_config_provider = None
        try:
            backend_config_provider = provider.get_service(
                IBackendConfigProvider  # type: ignore[type-abstract]
            )
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"BackendConfigProvider not available, will create default: {e}"
                )

        # If not available, create one with the app config
        if backend_config_provider is None:
            from src.core.services.backend_config_provider import BackendConfigProvider

            backend_config_provider = BackendConfigProvider(app_config)

        # Optionally build a failover strategy based on feature flag
        failover_strategy = None
        try:
            if (
                app_state.get_use_failover_strategy()
                and failover_coordinator is not None
            ):
                from src.core.services.failover_strategy import DefaultFailoverStrategy

                failover_strategy = DefaultFailoverStrategy(failover_coordinator)
        except (AttributeError, ImportError, TypeError) as e:
            logging.getLogger(__name__).debug(
                "Failed to enable failover strategy: %s", e, exc_info=True
            )

        # Get routing service
        from src.core.services.backend_routing_service import BackendRoutingService

        routing_service = provider.get_service(BackendRoutingService)

        # Get or create resilience coordinator
        resilience_coordinator = provider.get_service(ResilienceCoordinator)

        # Resolve failure handling strategy from DI or construct from config (Phase 4B)
        failure_handling_strategy = _resolve_failure_strategy(
            provider, app_config, routing_service
        )

        # Get extracted services
        stream_formatting_service = provider.get_required_service(
            IStreamFormattingService  # type: ignore[type-abstract]
        )
        usage_tracking_wrapper = provider.get_required_service(
            IUsageTrackingWrapper  # type: ignore[type-abstract]
        )
        model_alias_resolver = provider.get_required_service(
            IModelAliasResolver  # type: ignore[type-abstract]
        )
        exception_normalizer = provider.get_required_service(
            IExceptionNormalizer  # type: ignore[type-abstract]
        )
        backend_lifecycle_manager = provider.get_required_service(
            IBackendLifecycleManager  # type: ignore[type-abstract]
        )
        planning_phase_manager = provider.get_required_service(
            IPlanningPhaseManager  # type: ignore[type-abstract]
        )
        reasoning_config_applicator = provider.get_required_service(
            IReasoningConfigApplicator  # type: ignore[type-abstract]
        )
        uri_parameter_applicator = provider.get_required_service(
            IURIParameterApplicator  # type: ignore[type-abstract]
        )
        usage_tracking_service = provider.get_service(
            IUsageTrackingService  # type: ignore[type-abstract]
        )

        # Get extracted collaborators
        stream_session_id_resolver = provider.get_required_service(
            IStreamSessionIdResolver  # type: ignore[type-abstract]
        )
        backend_model_resolver = provider.get_required_service(
            IBackendModelResolver  # type: ignore[type-abstract]
        )
        failover_planner = provider.get_required_service(
            IFailoverPlanner  # type: ignore[type-abstract]
        )
        backend_completion_flow = provider.get_required_service(
            IBackendCompletionFlow  # type: ignore[type-abstract]
        )

        # Return backend service
        return BackendService(
            backend_factory,
            rate_limiter,
            app_config,
            session_service=provider.get_required_service(SessionService),
            app_state=app_state,
            backend_config_provider=backend_config_provider,
            failover_coordinator=failover_coordinator,
            failover_strategy=failover_strategy,
            wire_capture=provider.get_service(
                IWireCapture  # type: ignore[type-abstract]
            ),
            routing_service=routing_service,
            resilience_coordinator=resilience_coordinator,
            failure_handling_strategy=failure_handling_strategy,
            usage_tracking_service=usage_tracking_service,
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
        )

    # Register backend service and bind to interface
    _add_singleton(BackendService, implementation_factory=_backend_service_factory)

    try:
        services.add_singleton(
            cast(type, IBackendService), implementation_factory=_backend_service_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IBackendService interface: {e}")
        # Continue if concrete BackendService is registered

    # Register FailoverService first (dependency of FailoverCoordinator)
    def _failover_service_factory(provider: IServiceProvider) -> FailoverService:
        # FailoverService constructor takes failover_routes dict, defaulting to empty
        return FailoverService(failover_routes={})

    _add_singleton(FailoverService, implementation_factory=_failover_service_factory)

    # Register failover coordinator (if not already registered elsewhere as a concrete type)
    def _failover_coordinator_factory(
        provider: IServiceProvider,
    ) -> FailoverCoordinator:
        from src.core.services.failover_coordinator import FailoverCoordinator
        from src.core.services.failover_service import FailoverService

        failover_service = provider.get_required_service(FailoverService)
        return FailoverCoordinator(failover_service)

    from src.core.services.failover_coordinator import FailoverCoordinator

    _add_singleton(
        FailoverCoordinator, implementation_factory=_failover_coordinator_factory
    )

    try:
        from src.core.interfaces.failover_interface import IFailoverCoordinator

        services.add_singleton(
            cast(type, IFailoverCoordinator),
            implementation_factory=_failover_coordinator_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IFailoverCoordinator interface: {e}")
        # Continue if concrete FailoverCoordinator is registered

    # Register model replacement service
    def _model_replacement_service_factory(
        provider: IServiceProvider,
    ) -> ModelReplacementService | None:
        """Factory for creating ModelReplacementService.

        Returns None if replacement is disabled in config.
        """
        from src.core.services.backend_registry import BackendRegistry
        from src.core.services.model_replacement_service import ModelReplacementService

        app_config: AppConfig = provider.get_required_service(AppConfig)

        # Check if replacement is enabled
        if not app_config.replacement.enabled:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Model replacement is disabled in configuration")
            return None

        # Get backend registry
        backend_registry: BackendRegistry = provider.get_required_service(
            BackendRegistry
        )

        # Create and return the service
        return ModelReplacementService(
            config=app_config.replacement,
            backend_registry=backend_registry,
        )

    # Register the concrete service
    _add_singleton(
        ModelReplacementService,
        implementation_factory=_model_replacement_service_factory,
    )

    # Register the interface
    try:
        from src.core.interfaces.model_replacement_service_interface import (
            IModelReplacementService,
        )

        services.add_singleton(
            cast(type, IModelReplacementService),
            implementation_factory=_model_replacement_service_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IModelReplacementService interface: {e}"
            )
        # Continue if concrete ModelReplacementService is registered

    # Register request processor
    def _request_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        from src.core.interfaces.request_processor_internal import (
            IBackendExecutor,
            IBackendPreparer,
            ICommandHandler,
            IRequestSideEffects,
            IRequestTransformPipeline,
            ISessionEnricher,
        )

        # Get required services
        command_processor = provider.get_required_service(
            ICommandProcessor  # type: ignore[type-abstract]
        )
        session_manager = provider.get_required_service(
            ISessionManager  # type: ignore[type-abstract]
        )
        backend_request_manager = provider.get_required_service(
            IBackendRequestManager  # type: ignore[type-abstract]
        )
        response_manager = provider.get_required_service(
            IResponseManager  # type: ignore[type-abstract]
        )
        app_state = provider.get_service(
            IApplicationState  # type: ignore[type-abstract]
        )

        # Get replacement service (optional)
        replacement_service = provider.get_service(ModelReplacementService)

        # Get new required dependencies
        session_enricher = provider.get_required_service(
            ISessionEnricher  # type: ignore[type-abstract]
        )
        request_side_effects = provider.get_required_service(
            IRequestSideEffects  # type: ignore[type-abstract]
        )
        command_handler = provider.get_required_service(
            ICommandHandler  # type: ignore[type-abstract]
        )
        backend_preparer = provider.get_required_service(
            IBackendPreparer  # type: ignore[type-abstract]
        )
        transform_pipeline = provider.get_required_service(
            IRequestTransformPipeline  # type: ignore[type-abstract]
        )
        backend_executor = provider.get_required_service(
            IBackendExecutor  # type: ignore[type-abstract]
        )

        # Return request processor with decomposed services
        return RequestProcessor(
            command_processor,
            session_manager,
            backend_request_manager,
            response_manager,
            session_enricher=session_enricher,
            request_side_effects=request_side_effects,
            command_handler=command_handler,
            backend_preparer=backend_preparer,
            transform_pipeline=transform_pipeline,
            backend_executor=backend_executor,
            app_state=app_state,
            replacement_service=replacement_service,
        )

    # Register request processor and bind to interface
    _add_singleton(RequestProcessor, implementation_factory=_request_processor_factory)

    try:
        _add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IRequestProcessor interface: {e}")
        # Continue if concrete RequestProcessor is registered

    # Register extracted backend service collaborators
    from src.core.interfaces.backend_completion_flow_interface import (
        IBackendCompletionFlow,
    )
    from src.core.interfaces.backend_model_resolver_interface import (
        IBackendModelResolver,
    )
    from src.core.interfaces.failover_interface import (
        IFailoverCoordinator,
        IFailoverStrategy,
    )
    from src.core.interfaces.failover_planner_interface import IFailoverPlanner
    from src.core.interfaces.resilience_interface import IResilienceCoordinator
    from src.core.interfaces.stream_session_id_resolver_interface import (
        IStreamSessionIdResolver,
    )
    from src.core.services.backend_completion_flow import BackendCompletionFlow
    from src.core.services.backend_model_resolver import BackendModelResolver
    from src.core.services.failover_planner import FailoverPlanner
    from src.core.services.stream_session_id_resolver import StreamSessionIdResolver

    # Register stream session ID resolver (actual implementation)
    _add_singleton(StreamSessionIdResolver)
    try:
        _add_singleton(
            cast(type, IStreamSessionIdResolver),
            implementation_factory=lambda p: p.get_required_service(
                StreamSessionIdResolver
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Failed to register IStreamSessionIdResolver interface: {e}")

    # Register backend model resolver (actual implementation)
    _add_singleton(
        BackendModelResolver,
        implementation_factory=lambda p: BackendModelResolver(
            session_service=p.get_required_service(ISessionService),  # type: ignore[type-abstract]
            model_alias_resolver=p.get_required_service(IModelAliasResolver),  # type: ignore[type-abstract]
            planning_phase_manager=p.get_required_service(IPlanningPhaseManager),  # type: ignore[type-abstract]
            backend_lifecycle_manager=p.get_required_service(IBackendLifecycleManager),  # type: ignore[type-abstract]
            config=p.get_required_service(IConfig),  # type: ignore[type-abstract]
            routing_service=p.get_service(BackendRoutingService),
        ),
    )
    try:
        _add_singleton(
            cast(type, IBackendModelResolver),
            implementation_factory=lambda p: p.get_required_service(
                BackendModelResolver
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Failed to register IBackendModelResolver interface: {e}")

    # Register failover planner (actual implementation)
    _add_singleton(
        FailoverPlanner,
        implementation_factory=lambda p: FailoverPlanner(
            app_state=p.get_required_service(IApplicationState),  # type: ignore[type-abstract]
            failover_coordinator=p.get_required_service(IFailoverCoordinator),  # type: ignore[type-abstract]
            backend_lifecycle_manager=p.get_required_service(IBackendLifecycleManager),  # type: ignore[type-abstract]
            config=p.get_required_service(IConfig),  # type: ignore[type-abstract]
            failover_strategy=p.get_service(IFailoverStrategy),  # type: ignore[type-abstract]
            resilience_coordinator=p.get_service(IResilienceCoordinator),  # type: ignore[type-abstract]
        ),
    )
    try:
        _add_singleton(
            cast(type, IFailoverPlanner),
            implementation_factory=lambda p: p.get_required_service(FailoverPlanner),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Failed to register IFailoverPlanner interface: {e}")

    # Register backend completion flow (actual implementation)
    def _backend_completion_flow_factory(p: IServiceProvider) -> BackendCompletionFlow:
        """Factory for BackendCompletionFlow with all dependencies."""
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )
        from src.core.interfaces.backend_factory_interface import IBackendFactory
        from src.core.interfaces.backend_lifecycle_manager_interface import (
            IBackendLifecycleManager,
        )
        from src.core.interfaces.configuration_interface import IConfig
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.failure_strategy_interface import (
            IFailureHandlingStrategy,
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
        from src.core.interfaces.uri_parameter_applicator_interface import (
            IURIParameterApplicator,
        )
        from src.core.interfaces.usage_tracking_interface import IUsageTrackingService
        from src.core.interfaces.usage_tracking_wrapper_interface import (
            IUsageTrackingWrapper,
        )
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.backend_routing_service import BackendRoutingService

        # Get app config to extract failover_routes
        config = p.get_required_service(IConfig)  # type: ignore[type-abstract]
        failover_routes: dict[str, dict[Any, Any]] = {}
        if hasattr(config, "failover_routes"):
            failover_routes = getattr(config, "failover_routes", {})

        return BackendCompletionFlow(
            backend_model_resolver=p.get_required_service(IBackendModelResolver),  # type: ignore[type-abstract]
            stream_session_id_resolver=p.get_required_service(IStreamSessionIdResolver),  # type: ignore[type-abstract]
            failover_planner=p.get_required_service(IFailoverPlanner),  # type: ignore[type-abstract]
            session_service=p.get_required_service(ISessionService),  # type: ignore[type-abstract]
            backend_lifecycle_manager=p.get_required_service(IBackendLifecycleManager),  # type: ignore[type-abstract]
            backend_config_service=p.get_required_service(IBackendConfigProvider),  # type: ignore[type-abstract]
            reasoning_config_applicator=p.get_required_service(
                IReasoningConfigApplicator  # type: ignore[type-abstract]
            ),
            uri_parameter_applicator=p.get_required_service(IURIParameterApplicator),  # type: ignore[type-abstract]
            stream_formatting_service=p.get_required_service(IStreamFormattingService),  # type: ignore[type-abstract]
            usage_tracking_wrapper=p.get_required_service(IUsageTrackingWrapper),  # type: ignore[type-abstract]
            exception_normalizer=p.get_required_service(IExceptionNormalizer),  # type: ignore[type-abstract]
            planning_phase_manager=p.get_required_service(IPlanningPhaseManager),  # type: ignore[type-abstract]
            backend_factory=p.get_required_service(IBackendFactory),  # type: ignore[type-abstract]
            config=config,
            app_state=p.get_required_service(IApplicationState),  # type: ignore[type-abstract]
            failover_coordinator=p.get_required_service(IFailoverCoordinator),  # type: ignore[type-abstract]
            wire_capture=p.get_service(IWireCapture),  # type: ignore[type-abstract]
            usage_tracking_service=p.get_service(IUsageTrackingService),  # type: ignore[type-abstract]
            resilience_coordinator=p.get_service(IResilienceCoordinator),  # type: ignore[type-abstract]
            failure_handling_strategy=p.get_service(IFailureHandlingStrategy),  # type: ignore[type-abstract]
            routing_service=p.get_service(BackendRoutingService),
            failover_routes=failover_routes,
        )

    _add_singleton(
        BackendCompletionFlow, implementation_factory=_backend_completion_flow_factory
    )
    try:
        _add_singleton(
            cast(type, IBackendCompletionFlow),
            implementation_factory=lambda p: p.get_required_service(
                BackendCompletionFlow
            ),
        )  # type: ignore[type-abstract]
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Failed to register IBackendCompletionFlow interface: {e}")


def get_service(service_type: type[T]) -> T | None:
    """Get a service from the global service provider.

    Args:
        service_type: The type of service to get

    Returns:
        The service instance, or None if the service is not registered
    """
    provider = get_or_build_service_provider()
    return provider.get_service(service_type)  # type: ignore


def get_required_service(service_type: type[T]) -> T:
    """Get a required service from the global service provider.

    Args:
        service_type: The type of service to get

    Returns:
        The service instance

    Raises:
        Exception: If the service is not registered
    """
    provider = get_or_build_service_provider()
    return provider.get_required_service(service_type)  # type: ignore
