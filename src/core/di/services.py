"""
Services and DI container configuration.

This module provides functions for configuring the DI container with services
and resolving services from the container.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar, cast

from src.core.common.exceptions import ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    LoopDetectionProcessor,
)
from src.core.interfaces.agent_response_formatter_interface import (
    IAgentResponseFormatter,
)
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_config_provider_interface import (
    IBackendConfigProvider,
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
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
)
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.app_settings_service import AppSettings
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.backend_service import BackendService
from src.core.services.command_processor import CommandProcessor
from src.core.services.dangerous_command_service import DangerousCommandService
from src.core.services.failover_service import FailoverService
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)
from src.core.services.pytest_compression_service import PytestCompressionService
from src.core.services.request_processor_service import RequestProcessor
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
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.structured_output_middleware import StructuredOutputMiddleware
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
from src.core.services.tool_call_reactor_service import (
    InMemoryToolCallHistoryTracker,
    ToolCallReactorService,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.core.services.translation_service import TranslationService

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
            logging.getLogger(__name__).exception(
                "Failed to register core services into global service collection"
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
            logging.getLogger("llm.di").info(
                "Building service provider; descriptors=%d",
                len(get_service_collection()._descriptors),
            )
        _service_provider = get_service_collection().build_service_provider()
    return _service_provider


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
        A provider that can resolve the ToolCallReactor service and middleware.

    Raises:
        ServiceResolutionError: If re-registration fails to provide the required services.
    """

    from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
    from src.core.services.tool_call_reactor_service import ToolCallReactorService

    missing_components: list[str] = []

    if provider.get_service(ToolCallReactorService) is None:
        missing_components.append("ToolCallReactorService")
    if provider.get_service(ToolCallReactorMiddleware) is None:
        missing_components.append("ToolCallReactorMiddleware")

    if not missing_components:
        return provider

    logger = logging.getLogger(__name__)
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
    if new_provider.get_service(ToolCallReactorMiddleware) is None:
        still_missing.append("ToolCallReactorMiddleware")

    if still_missing:
        raise ServiceResolutionError(
            "Failed to register required Tool Call Reactor services.",
            details={"missing_components": still_missing},
        )

    return new_provider


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
        logging.getLogger(__name__).warning(
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
        logger.warning(f"Failed to register response handler interfaces: {e}")
        # Continue if concrete handlers are registered

    # Register MiddlewareApplicationManager and IMiddlewareApplicationManager with configured middleware list
    def _middleware_application_manager_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationManager:
        from src.core.app.middleware.json_repair_middleware import JsonRepairMiddleware
        from src.core.app.middleware.tool_call_repair_middleware import (
            ToolCallRepairMiddleware,
        )
        from src.core.config.app_config import AppConfig
        from src.core.services.empty_response_middleware import (
            EmptyResponseMiddleware,
        )
        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )
        from src.core.services.tool_call_loop_middleware import (
            ToolCallLoopDetectionMiddleware,
        )

        cfg: AppConfig = provider.get_required_service(AppConfig)
        middlewares: list[IResponseMiddleware] = []

        try:
            if getattr(cfg.empty_response, "enabled", True):
                middlewares.append(
                    EmptyResponseMiddleware(
                        enabled=True,
                        max_retries=getattr(cfg.empty_response, "max_retries", 1),
                    )
                )
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring EmptyResponseMiddleware: {e}", exc_info=True
            )

        # Edit-precision response-side detection (optional)
        try:
            from src.core.services.edit_precision_response_middleware import (
                EditPrecisionResponseMiddleware,
            )

            app_state = provider.get_required_service(ApplicationStateService)
            middlewares.append(EditPrecisionResponseMiddleware(app_state))
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring EditPrecisionResponseMiddleware: {e}",
                exc_info=True,
            )

        # Think tags fix middleware (optional)
        try:
            if getattr(cfg.session, "fix_think_tags_enabled", False):
                from src.core.services.think_tags_fix_middleware import (
                    ThinkTagsFixMiddleware,
                )

                # Configure streaming buffer size from config
                buffer_size = getattr(
                    cfg.session, "fix_think_tags_streaming_buffer_size", 4096
                )
                middlewares.append(
                    ThinkTagsFixMiddleware(
                        enabled=True, streaming_buffer_size=buffer_size
                    )
                )
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring ThinkTagsFixMiddleware: {e}",
                exc_info=True,
            )

        if getattr(cfg.session, "json_repair_enabled", False):
            json_service: JsonRepairService = provider.get_required_service(
                JsonRepairService
            )
            middlewares.append(JsonRepairMiddleware(cfg, json_service))

        if getattr(cfg.session, "tool_call_repair_enabled", True):
            tcr_service: ToolCallRepairService = provider.get_required_service(
                ToolCallRepairService
            )
            middlewares.append(ToolCallRepairMiddleware(cfg, tcr_service))

        try:
            middlewares.append(ToolCallLoopDetectionMiddleware())
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring ToolCallLoopDetectionMiddleware: {e}", exc_info=True
            )

        # Add tool call reactor middleware
        try:
            tool_call_reactor_middleware = provider.get_required_service(
                ToolCallReactorMiddleware
            )
            middlewares.append(tool_call_reactor_middleware)
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring ToolCallReactorMiddleware: {e}", exc_info=True
            )

        # Dangerous command prevention will be handled by Tool Call Reactor handler.
        # Keeping old middleware disabled to avoid duplicate processing.

        return MiddlewareApplicationManager(middlewares)

    _add_singleton(
        MiddlewareApplicationManager,
        implementation_factory=_middleware_application_manager_factory,
    )
    try:
        services.add_singleton(
            cast(type, IMiddlewareApplicationManager),
            implementation_factory=_middleware_application_manager_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        logger.warning(
            f"Failed to register IMiddlewareApplicationManager interface: {e}"
        )
        # Continue if concrete MiddlewareApplicationManager is registered

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
        return MiddlewareApplicationProcessor(manager._middleware, app_state=app_state)

    _add_singleton(
        MiddlewareApplicationProcessor,
        implementation_factory=_middleware_application_processor_factory,
    )

    # Register response processor
    def _response_processor_factory(provider: IServiceProvider) -> ResponseProcessor:
        from typing import cast

        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)
        )
        stream_normalizer: IStreamNormalizer = provider.get_required_service(
            cast(type, IStreamNormalizer)
        )
        response_parser: IResponseParser = provider.get_required_service(
            cast(type, IResponseParser)
        )
        middleware_application_manager: IMiddlewareApplicationManager = (
            provider.get_required_service(cast(type, IMiddlewareApplicationManager))
        )

        # Get the middleware manager to access the middleware list
        middleware_manager: MiddlewareApplicationManager = (
            provider.get_required_service(MiddlewareApplicationManager)
        )

        # Get loop detector for non-streaming responses
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        loop_detector = provider.get_service(cast(type, ILoopDetector))

        return ResponseProcessor(
            response_parser=response_parser,
            middleware_application_manager=middleware_application_manager,
            app_state=app_state,
            loop_detector=loop_detector,
            stream_normalizer=stream_normalizer,
            middleware_list=middleware_manager._middleware,
        )

    # Register response processor and bind to interface
    _add_singleton(
        ResponseProcessor, implementation_factory=_response_processor_factory
    )

    try:
        services.add_singleton(
            cast(type, IResponseProcessor),
            implementation_factory=_response_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        logger.warning(f"Failed to register IResponseProcessor interface: {e}")
        # Continue if concrete ResponseProcessor is registered

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
            logger.debug(f"Could not get app_state from ApplicationStateService: {e}")
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
        logger.warning(f"Failed to register IResponseManager interface: {e}")
        # Continue if concrete ResponseManager is registered

    # Register backend request manager
    def _backend_request_manager_factory(
        provider: IServiceProvider,
    ) -> BackendRequestManager:
        backend_processor = provider.get_required_service(IBackendProcessor)  # type: ignore[type-abstract]
        response_processor = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]
        wire_capture = provider.get_required_service(IWireCapture)  # type: ignore[type-abstract]
        return BackendRequestManager(
            backend_processor, response_processor, wire_capture
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
        logger.warning(f"Failed to register IBackendRequestManager interface: {e}")
        # Continue if concrete BackendRequestManager is registered

    # Register stream normalizer
    def _stream_normalizer_factory(provider: IServiceProvider) -> StreamNormalizer:
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
                    LoopDetectionProcessor
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "LoopDetectionProcessor successfully registered for streaming"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to register LoopDetectionProcessor for streaming: {e}"
                )
                loop_detection_processor = None
            middleware_application_processor = provider.get_required_service(
                MiddlewareApplicationProcessor
            )
            content_accumulation_processor = provider.get_required_service(
                ContentAccumulationProcessor
            )

            processors: list[IStreamProcessor] = []
            # Prefer JSON repair first so JSON blocks are valid
            if json_repair_processor is not None:
                processors.append(json_repair_processor)
            # Then text loop detection
            if loop_detection_processor is not None:
                processors.append(loop_detection_processor)
            # Then tool-call repair
            if tool_call_repair_processor is not None:
                processors.append(tool_call_repair_processor)
            # Middleware and accumulation
            processors.append(middleware_application_processor)
            processors.append(content_accumulation_processor)
        except Exception as e:
            logger.warning(
                f"Error creating stream processors: {e}. Using default configuration."
            )
            # Create minimal configuration with just content accumulation
            # Use default 10MB buffer limit for fallback
            content_accumulation_processor = ContentAccumulationProcessor(
                max_buffer_bytes=10 * 1024 * 1024
            )
            processors = [content_accumulation_processor]

        return StreamNormalizer(processors)

    _add_singleton(StreamNormalizer, implementation_factory=_stream_normalizer_factory)

    try:
        services.add_singleton(
            cast(type, IStreamNormalizer),
            implementation_factory=_stream_normalizer_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
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
        logger.warning(f"Failed to register IResponseParser interface: {e}")
        # Continue if concrete ResponseParser is registered

    # Register individual stream processors
    def _loop_detection_processor_factory(
        provider: IServiceProvider,
    ) -> LoopDetectionProcessor:
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        loop_detector: ILoopDetector = provider.get_required_service(
            cast(type, ILoopDetector)
        )
        return LoopDetectionProcessor(loop_detector)

    _add_singleton(
        LoopDetectionProcessor, implementation_factory=_loop_detection_processor_factory
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
        return ContentAccumulationProcessor(max_buffer_bytes=buffer_cap)

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
        return JsonRepairProcessor(
            repair_service=service,
            buffer_cap_bytes=getattr(
                config.session, "json_repair_buffer_cap_bytes", 64 * 1024
            ),
            strict_mode=getattr(config.session, "json_repair_strict_mode", False),
            schema=getattr(config.session, "json_repair_schema", None),
            enabled=getattr(config.session, "json_repair_enabled", False),
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

    # Register TranslationService (dependency of BackendService)
    def _translation_service_factory(provider: IServiceProvider) -> TranslationService:
        return TranslationService()

    _add_singleton(
        TranslationService, implementation_factory=_translation_service_factory
    )

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
        logger.warning(f"Failed to register IToolCallRepairService interface: {e}")
        # Continue if concrete ToolCallRepairService is registered

    # Register tool call repair processor
    def _tool_call_repair_processor_factory(
        provider: IServiceProvider,
    ) -> ToolCallRepairProcessor:
        tool_call_repair_service = provider.get_required_service(IToolCallRepairService)  # type: ignore[type-abstract]
        return ToolCallRepairProcessor(tool_call_repair_service)

    _add_singleton(
        ToolCallRepairProcessor,
        implementation_factory=_tool_call_repair_processor_factory,
    )

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
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )
            from src.core.services.tool_call_handlers.dangerous_command_handler import (
                DangerousCommandHandler,
            )
            from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
                PytestFullSuiteHandler,
            )

            # Register config-driven steering handler (includes synthesized legacy apply_diff rule when enabled)
            try:
                # Build effective rules from config while avoiding expensive deep copy.
                # Since steering_rules are configuration data (immutable during runtime),
                # we can safely use a shallow copy for better performance.
                effective_rules = (
                    (reactor_config.steering_rules or []).copy()
                    if reactor_config.steering_rules
                    else []
                )

                # Synthesize legacy apply_diff rule if enabled and missing
                if getattr(reactor_config, "apply_diff_steering_enabled", True):
                    has_apply_rule = False
                    for r in effective_rules:
                        triggers = (r or {}).get("triggers") or {}
                        tnames = triggers.get("tool_names") or []
                        phrases = triggers.get("phrases") or []
                        if "apply_diff" in tnames or any(
                            isinstance(p, str) and "apply_diff" in p for p in phrases
                        ):
                            has_apply_rule = True
                            break
                    if not has_apply_rule:
                        effective_rules.append(
                            {
                                "name": "apply_diff_to_patch_file",
                                "enabled": True,
                                "priority": 100,
                                "triggers": {
                                    "tool_names": ["apply_diff"],
                                    "phrases": [],
                                },
                                "message": (
                                    reactor_config.apply_diff_steering_message
                                    or (
                                        "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, "
                                        "as it is superior to apply_diff and provides automated Python QA checks."
                                    )
                                ),
                                "rate_limit": {
                                    "calls_per_window": 1,
                                    "window_seconds": reactor_config.apply_diff_steering_rate_limit_seconds,
                                },
                            }
                        )

                if effective_rules:
                    config_handler = ConfigSteeringHandler(rules=effective_rules)
                    try:
                        reactor.register_handler_sync(config_handler)
                    except Exception as e:
                        logger.warning(
                            f"Failed to register config steering handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    "Failed to register steering handlers: %s", e, exc_info=True
                )

            # Register DangerousCommandHandler if enabled in session config
            try:
                if getattr(
                    app_config.session, "dangerous_command_prevention_enabled", True
                ):
                    dangerous_service = provider.get_required_service(
                        DangerousCommandService
                    )
                    dangerous_handler = DangerousCommandHandler(
                        dangerous_service,
                        steering_message=getattr(
                            app_config.session,
                            "dangerous_command_steering_message",
                            None,
                        ),
                        enabled=True,
                    )
                    try:
                        reactor.register_handler_sync(dangerous_handler)
                    except Exception as e:
                        logger.warning(
                            f"Failed to register dangerous command handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to register DangerousCommandHandler: {e}", exc_info=True
                )

            # Register PytestFullSuiteHandler if enabled
            try:
                if getattr(reactor_config, "pytest_full_suite_steering_enabled", False):
                    steering_message = getattr(
                        reactor_config, "pytest_full_suite_steering_message", None
                    )
                    pytest_full_suite_handler = PytestFullSuiteHandler(
                        message=steering_message,
                        enabled=True,
                    )
                    try:
                        reactor.register_handler_sync(pytest_full_suite_handler)
                    except Exception as e:
                        logger.warning(
                            f"Failed to register pytest full-suite handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to register PytestFullSuiteHandler: {e}", exc_info=True
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
                        logger.warning(
                            f"Failed to register pytest context saving handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to register PytestContextSavingHandler: {e}", exc_info=True
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
                        logger.warning(
                            f"Failed to register pytest compression handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to register PytestCompressionHandler: {e}", exc_info=True
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
                        logger.info(
                            f"Registered ToolAccessControlHandler with priority 90 "
                            f"({len(policy_service._policies)} policies loaded)"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to register tool access control handler: {e}",
                            exc_info=True,
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to register ToolAccessControlHandler: {e}", exc_info=True
                )

        return reactor

    _add_singleton(
        ToolCallReactorService,
        implementation_factory=_tool_call_reactor_factory,
    )

    def _tool_call_reactor_middleware_factory(
        provider: IServiceProvider,
    ) -> ToolCallReactorMiddleware:
        from src.core.config.app_config import AppConfig

        reactor = provider.get_required_service(ToolCallReactorService)

        # Get configuration to determine if middleware should be enabled
        app_config: AppConfig = provider.get_required_service(AppConfig)
        enabled = app_config.session.tool_call_reactor.enabled

        return ToolCallReactorMiddleware(reactor, enabled=enabled, priority=-10)

    _add_singleton(
        ToolCallReactorMiddleware,
        implementation_factory=_tool_call_reactor_middleware_factory,
    )

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
        app_state: IApplicationState = provider.get_required_service(IApplicationState)  # type: ignore[type-abstract]

        # Get failover coordinator (optional for test environments)
        failover_coordinator = None
        try:
            failover_coordinator = provider.get_service(IFailoverCoordinator)  # type: ignore[type-abstract]
        except Exception as e:
            logger.debug(f"FailoverCoordinator not available: {e}")

        # Get backend config provider or create one
        backend_config_provider = None
        try:
            backend_config_provider = provider.get_service(IBackendConfigProvider)  # type: ignore[type-abstract]
        except Exception as e:
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
            wire_capture=provider.get_required_service(IWireCapture),  # type: ignore[type-abstract]
        )

    # Register backend service and bind to interface
    _add_singleton(BackendService, implementation_factory=_backend_service_factory)

    try:
        services.add_singleton(
            cast(type, IBackendService), implementation_factory=_backend_service_factory
        )  # type: ignore[type-abstract]
    except Exception as e:
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
        logger.warning(f"Failed to register IFailoverCoordinator interface: {e}")
        # Continue if concrete FailoverCoordinator is registered

    # Register request processor
    def _request_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        # Get required services
        command_processor = provider.get_required_service(ICommandProcessor)  # type: ignore[type-abstract]
        session_manager = provider.get_required_service(ISessionManager)  # type: ignore[type-abstract]
        backend_request_manager = provider.get_required_service(IBackendRequestManager)  # type: ignore[type-abstract]
        response_manager = provider.get_required_service(IResponseManager)  # type: ignore[type-abstract]
        app_state = provider.get_service(IApplicationState)  # type: ignore[type-abstract]

        # Return request processor with decomposed services
        return RequestProcessor(
            command_processor,
            session_manager,
            backend_request_manager,
            response_manager,
            app_state=app_state,
        )

    # Register request processor and bind to interface
    _add_singleton(RequestProcessor, implementation_factory=_request_processor_factory)

    try:
        _add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )  # type: ignore[type-abstract]
    except Exception as e:
        logger.warning(f"Failed to register IRequestProcessor interface: {e}")
        # Continue if concrete RequestProcessor is registered


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
