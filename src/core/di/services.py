"""
Services and DI container configuration.

This module provides functions for configuring the DI container with services
and resolving services from the container.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

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
from src.core.services.command_argument_parser import CommandArgumentParser
from src.core.services.command_processor import CommandProcessor
from src.core.services.command_sanitizer import CommandSanitizer
from src.core.services.command_service import CommandService
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)
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
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.core.services.wire_capture_service import WireCapture

T = TypeVar("T")

# Global service collection
_service_collection: ServiceCollection | None = None
_service_provider: IServiceProvider | None = None


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
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to register core services into global service collection"
            )
    return _service_collection


def get_or_build_service_provider() -> IServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    Returns:
        The global service provider
    """
    global _service_provider
    if _service_provider is None:
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
    return get_or_build_service_provider()


def register_core_services(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register core services with the service collection.

    Args:
        services: The service collection to register services with
        app_config: Optional application configuration
    """
    # Register AppConfig and IConfig
    if app_config is not None:
        services.add_instance(AppConfig, app_config)
        # Also register it as IConfig for interface resolution
        with contextlib.suppress(Exception):
            services.add_instance(
                cast(type, IConfig),
                app_config,
            )  # type: ignore[type-abstract]
    else:
        # Register default AppConfig as IConfig for testing and basic functionality
        default_config = AppConfig()
        services.add_instance(AppConfig, default_config)
        with contextlib.suppress(Exception):
            services.add_instance(
                cast(type, IConfig),
                default_config,
            )  # type: ignore[type-abstract]

    # Helper wrappers to make registration idempotent and provide debug logging
    logger: logging.Logger = logging.getLogger(__name__)

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

    # Register CommandRegistry
    from src.core.services.command_service import CommandRegistry

    _add_singleton(CommandRegistry)

    # Register CommandService with factory
    def _command_service_factory(provider: IServiceProvider) -> CommandService:
        registry: CommandRegistry = provider.get_required_service(CommandRegistry)
        session_svc: SessionService = provider.get_required_service(SessionService)
        # Inject new parser/sanitizer; keep service construction resilient
        argument_parser = CommandArgumentParser()
        command_sanitizer = CommandSanitizer()
        return CommandService(
            registry,
            session_svc,
            argument_parser=argument_parser,
            command_sanitizer=command_sanitizer,
        )

    # Register CommandService and bind to interface
    _add_singleton(CommandService, implementation_factory=_command_service_factory)

    # Register ICommandService interface
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, ICommandService), implementation_factory=_command_service_factory
        )  # type: ignore[type-abstract]

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

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, ISessionService), implementation_factory=_session_service_factory
        )  # type: ignore[type-abstract]

    # Register command processor
    def _command_processor_factory(provider: IServiceProvider) -> CommandProcessor:
        # Get command service
        from typing import cast

        command_service: ICommandService = provider.get_required_service(
            cast(type, ICommandService)
        )

        # Return command processor
        return CommandProcessor(command_service)

    # Register command processor and bind to interface
    _add_singleton(CommandProcessor, implementation_factory=_command_processor_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, ICommandProcessor),
            implementation_factory=_command_processor_factory,
        )  # type: ignore[type-abstract]

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

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendProcessor),
            implementation_factory=_backend_processor_factory,
        )  # type: ignore[type-abstract]

    # Register response handlers
    _add_singleton(DefaultNonStreamingResponseHandler)
    _add_singleton(DefaultStreamingResponseHandler)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, INonStreamingResponseHandler), DefaultNonStreamingResponseHandler
        )
        services.add_singleton(
            cast(type, IStreamingResponseHandler), DefaultStreamingResponseHandler
        )

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

            middlewares.append(EditPrecisionResponseMiddleware())
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Error configuring EditPrecisionResponseMiddleware: {e}",
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

        return MiddlewareApplicationManager(middlewares)

    _add_singleton(
        MiddlewareApplicationManager,
        implementation_factory=_middleware_application_manager_factory,
    )
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IMiddlewareApplicationManager),
            implementation_factory=_middleware_application_manager_factory,
        )  # type: ignore[type-abstract]

    # Register MiddlewareApplicationProcessor used inside the streaming pipeline
    def _middleware_application_processor_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationProcessor:
        manager: MiddlewareApplicationManager = provider.get_required_service(
            MiddlewareApplicationManager
        )
        return MiddlewareApplicationProcessor(manager._middleware)

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

        return ResponseProcessor(
            app_state=app_state,
            response_parser=response_parser,
            middleware_application_manager=middleware_application_manager,
            stream_normalizer=stream_normalizer,
            middleware_list=middleware_manager._middleware,
        )

    # Register response processor and bind to interface
    _add_singleton(
        ResponseProcessor, implementation_factory=_response_processor_factory
    )

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IResponseProcessor),
            implementation_factory=_response_processor_factory,
        )  # type: ignore[type-abstract]

    # Register app settings
    def _app_settings_factory(provider: IServiceProvider) -> AppSettings:
        # Get app_state from IApplicationState if available
        app_state: Any | None = None
        with contextlib.suppress(Exception):
            app_state_service: IApplicationState | None = provider.get_service(
                ApplicationStateService
            )
            if app_state_service:
                app_state = app_state_service.get_setting("service_provider")

        # Create app settings
        return AppSettings(app_state)

    # Register app settings and bind to interface
    _add_singleton(AppSettings, implementation_factory=_app_settings_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IAppSettings), implementation_factory=_app_settings_factory
        )  # type: ignore[type-abstract]

    # Register application state service
    def _application_state_factory(
        provider: IServiceProvider,
    ) -> ApplicationStateService:
        # Check if we already have a cached singleton instance (e.g., from test setup)
        descriptors = getattr(provider, "_descriptors", {})
        descriptor = descriptors.get(ApplicationStateService)
        if descriptor and descriptor.instance is not None:
            return cast(ApplicationStateService, descriptor.instance)

        # Create a single ApplicationStateService and also sync it to the
        # global default to maintain compatibility with tests that use
        # get_default_application_state() to mutate flags.
        instance = ApplicationStateService()
        try:
            from src.core.services.application_state_service import (
                set_default_application_state,
            )

            set_default_application_state(instance)
        except Exception:
            pass
        return instance

    _add_singleton(
        ApplicationStateService, implementation_factory=_application_state_factory
    )

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IApplicationState),
            implementation_factory=_application_state_factory,
        )  # type: ignore[type-abstract]

    # Register secure state service
    def _secure_state_factory(provider: IServiceProvider) -> SecureStateService:
        app_state = provider.get_required_service(ApplicationStateService)
        return SecureStateService(app_state)

    _add_singleton(SecureStateService, implementation_factory=_secure_state_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, ISecureStateAccess), implementation_factory=_secure_state_factory
        )  # type: ignore[type-abstract]
        services.add_singleton(
            cast(type, ISecureStateModification),
            implementation_factory=_secure_state_factory,
        )  # type: ignore[type-abstract]

    # Register secure command factory
    def _secure_command_factory(provider: IServiceProvider) -> SecureCommandFactory:
        secure_state = provider.get_required_service(SecureStateService)
        return SecureCommandFactory(
            state_reader=secure_state, state_modifier=secure_state
        )

    _add_singleton(SecureCommandFactory, implementation_factory=_secure_command_factory)

    # Register session manager
    def _session_manager_factory(provider: IServiceProvider) -> SessionManager:
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        session_resolver = provider.get_required_service(ISessionResolver)  # type: ignore[type-abstract]
        return SessionManager(session_service, session_resolver)

    _add_singleton(SessionManager, implementation_factory=_session_manager_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, ISessionManager), implementation_factory=_session_manager_factory
        )  # type: ignore[type-abstract]

    # Register agent response formatter
    def _agent_response_formatter_factory(
        provider: IServiceProvider,
    ) -> AgentResponseFormatter:
        return AgentResponseFormatter()

    _add_singleton(
        AgentResponseFormatter, implementation_factory=_agent_response_formatter_factory
    )

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IAgentResponseFormatter),
            implementation_factory=_agent_response_formatter_factory,
        )  # type: ignore[type-abstract]

    # Register response manager
    def _response_manager_factory(provider: IServiceProvider) -> ResponseManager:
        agent_response_formatter = provider.get_required_service(IAgentResponseFormatter)  # type: ignore[type-abstract]
        return ResponseManager(agent_response_formatter)

    _add_singleton(ResponseManager, implementation_factory=_response_manager_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IResponseManager),
            implementation_factory=_response_manager_factory,
        )  # type: ignore[type-abstract]

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

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendRequestManager),
            implementation_factory=_backend_request_manager_factory,
        )  # type: ignore[type-abstract]

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
            except Exception:
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
            content_accumulation_processor = ContentAccumulationProcessor()
            processors = [content_accumulation_processor]

        return StreamNormalizer(processors)

    _add_singleton(StreamNormalizer, implementation_factory=_stream_normalizer_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IStreamNormalizer),
            implementation_factory=_stream_normalizer_factory,
        )  # type: ignore[type-abstract]

    # Register ResponseParser
    def _response_parser_factory(provider: IServiceProvider) -> ResponseParser:

        return ResponseParser()

    _add_singleton(ResponseParser, implementation_factory=_response_parser_factory)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IResponseParser), implementation_factory=_response_parser_factory
        )  # type: ignore[type-abstract]

    # Register individual stream processors
    _add_singleton(LoopDetectionProcessor)
    _add_singleton(ToolCallRepairProcessor)
    _add_singleton(ContentAccumulationProcessor)

    # Register JSON repair service and processor
    def _json_repair_service_factory(provider: IServiceProvider) -> JsonRepairService:
        return JsonRepairService()

    _add_singleton(
        JsonRepairService, implementation_factory=_json_repair_service_factory
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

    # Register wire-capture service (singleton)
    def _wire_capture_factory(provider: IServiceProvider) -> WireCapture:
        cfg: AppConfig = provider.get_required_service(AppConfig)
        return WireCapture(cfg)

    _add_singleton(WireCapture, implementation_factory=_wire_capture_factory)
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IWireCapture), implementation_factory=_wire_capture_factory
        )  # type: ignore[type-abstract]

    # Register tool call repair service (if not already registered elsewhere as a concrete type)
    def _tool_call_repair_service_factory(
        provider: IServiceProvider,
    ) -> ToolCallRepairService:
        return ToolCallRepairService()

    _add_singleton(
        ToolCallRepairService, implementation_factory=_tool_call_repair_service_factory
    )

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IToolCallRepairService),
            implementation_factory=_tool_call_repair_service_factory,
        )  # type: ignore[type-abstract]

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

    # Register backend service
    def _backend_service_factory(provider: IServiceProvider) -> BackendService:
        # Import required modules
        import httpx

        from src.core.services.backend_factory import BackendFactory
        from src.core.services.backend_registry import backend_registry
        from src.core.services.rate_limiter_service import RateLimiter

        # Get or create dependencies
        httpx_client: httpx.AsyncClient | None = provider.get_service(httpx.AsyncClient)
        if httpx_client is None:
            httpx_client = httpx.AsyncClient()

        # Get app config
        app_config: AppConfig = provider.get_required_service(AppConfig)

        # Create backend factory - always use real implementation, ignore any mocks
        # This ensures BackendService uses real backends even in test environments
        backend_factory: BackendFactory = BackendFactory(
            httpx_client, backend_registry, app_config
        )

        # Create rate limiter
        rate_limiter: RateLimiter = RateLimiter()

        # Get application state service
        app_state: IApplicationState = provider.get_required_service(IApplicationState)  # type: ignore[type-abstract]

        # Get failover coordinator (optional for test environments)
        failover_coordinator = None
        with contextlib.suppress(Exception):
            failover_coordinator = provider.get_service(IFailoverCoordinator)  # type: ignore[type-abstract]

        # Get backend config provider or create one
        backend_config_provider = None
        with contextlib.suppress(Exception):
            backend_config_provider = provider.get_service(IBackendConfigProvider)  # type: ignore[type-abstract]

        # If not available, create one with the app config
        if backend_config_provider is None:
            from src.core.services.backend_config_provider import BackendConfigProvider

            backend_config_provider = BackendConfigProvider(app_config)

        # Return backend service
        return BackendService(
            backend_factory,
            rate_limiter,
            app_config,
            session_service=provider.get_required_service(SessionService),
            app_state=app_state,
            backend_config_provider=backend_config_provider,
            failover_coordinator=failover_coordinator,
            wire_capture=provider.get_required_service(IWireCapture),  # type: ignore[type-abstract]
        )

    # Register backend service and bind to interface
    _add_singleton(BackendService, implementation_factory=_backend_service_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendService), implementation_factory=_backend_service_factory
        )  # type: ignore[type-abstract]

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

    with contextlib.suppress(Exception):
        from src.core.interfaces.failover_interface import IFailoverCoordinator

        services.add_singleton(
            cast(type, IFailoverCoordinator),
            implementation_factory=_failover_coordinator_factory,
        )  # type: ignore[type-abstract]

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

    with contextlib.suppress(Exception):
        _add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )  # type: ignore[type-abstract]


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
