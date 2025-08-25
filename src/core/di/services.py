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
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamingResponseProcessor,
)
from src.core.services.app_settings_service import AppSettings
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_service import BackendService
from src.core.services.command_processor import CommandProcessor
from src.core.services.command_service import CommandService
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.response_handlers import (
    DefaultNonStreamingResponseHandler,
    DefaultStreamingResponseHandler,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.secure_command_factory import SecureCommandFactory
from src.core.services.secure_state_service import SecureStateService
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.services.session_service_impl import SessionService
from src.core.services.streaming_response_processor_service import (
    StreamingResponseProcessorService,
)

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
    # Register AppConfig if provided
    if app_config is not None:
        services.add_instance(AppConfig, app_config)

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
        return CommandService(registry, session_svc)

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
        command_service: ICommandService = provider.get_required_service(
            ICommandService
        )  # type: ignore[type-abstract]

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
        backend_service: IBackendService = provider.get_required_service(
            IBackendService
        )  # type: ignore[type-abstract]
        session_service: ISessionService = provider.get_required_service(
            ISessionService
        )  # type: ignore[type-abstract]

        # Return backend processor (inject application state to adhere to DIP)
        app_state = provider.get_required_service(ApplicationStateService)
        return BackendProcessor(
            backend_service=backend_service,
            session_service=session_service,
            application_state=app_state,
        )

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

    # Register response processor
    def _response_processor_factory(provider: IServiceProvider) -> ResponseProcessor:
        # Get loop detector if available
        detector: Any | None = None
        try:
            from src.core.interfaces.loop_detector_interface import ILoopDetector

            detector = provider.get_service(cast(type, ILoopDetector))
        except Exception:
            pass

        # Create response processor with loop detector and middleware
        logger = logging.getLogger(__name__)
        try:
            # Import the LoopDetectionMiddleware
            # Create middleware list with explicit interface typing
            from src.core.interfaces.response_processor_interface import (
                IResponseMiddleware,
            )
            from src.core.services.empty_response_middleware import (
                EmptyResponseMiddleware,
            )
            from src.core.services.response_middleware import LoopDetectionMiddleware

            middleware: list[IResponseMiddleware] = []

            # Add empty response middleware
            try:
                app_config = provider.get_service(AppConfig)
                if app_config and hasattr(app_config, "empty_response"):
                    empty_response_config = app_config.empty_response
                    middleware.append(
                        EmptyResponseMiddleware(
                            enabled=empty_response_config.enabled,
                            max_retries=empty_response_config.max_retries,
                        )
                    )
                else:
                    # Default configuration if not available
                    middleware.append(EmptyResponseMiddleware())
                logger.debug("Added empty response middleware")
            except Exception as e:
                logger.warning(f"Empty response middleware not available: {e}")

            if detector:
                middleware.append(LoopDetectionMiddleware(detector))

                return ResponseProcessor(loop_detector=detector, middleware=middleware)
            return ResponseProcessor(middleware=middleware)
        except Exception as e:  # type: ignore[misc]
            logger.exception("Failed to create ResponseProcessor: %s", e)
            raise

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
        # Prefer injected state provider; create with no state provider for backward compatibility
        try:
            # Try to get a state provider from the service provider
            state_provider = provider.get_service(
                object
            )  # Generic object as we don't know the exact type
            if state_provider is not None:
                return ApplicationStateService(state_provider)
        except Exception:
            # If we can't get a state provider, fall back to creating without one
            pass
        return ApplicationStateService()

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

        # Create backend factory
        backend_factory: BackendFactory = BackendFactory(httpx_client, backend_registry)

        # Create rate limiter
        rate_limiter: RateLimiter = RateLimiter()

        app_state = provider.get_required_service(ApplicationStateService)
        # Return backend service
        return BackendService(
            backend_factory,
            rate_limiter,
            app_config,
            session_service=provider.get_required_service(SessionService),
            app_state=app_state,
        )

    # Register backend service and bind to interface
    _add_singleton(BackendService, implementation_factory=_backend_service_factory)

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IBackendService), implementation_factory=_backend_service_factory
        )  # type: ignore[type-abstract]

    # Register request processor
    def _request_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        # Import interface types inside the factory to avoid runtime name errors
        # if modules are imported in different orders during startup.
        from src.core.interfaces.backend_processor_interface import IBackendProcessor
        from src.core.interfaces.command_processor_interface import ICommandProcessor
        from src.core.interfaces.response_processor_interface import IResponseProcessor
        from src.core.interfaces.session_resolver_interface import ISessionResolver
        from src.core.interfaces.session_service_interface import ISessionService

        # Get required services
        command_proc: ICommandProcessor = provider.get_required_service(
            ICommandProcessor
        )  # type: ignore[type-abstract]
        backend_proc: IBackendProcessor = provider.get_required_service(
            IBackendProcessor
        )  # type: ignore[type-abstract]
        session_svc: ISessionService = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        response_proc: IResponseProcessor = provider.get_required_service(
            IResponseProcessor
        )  # type: ignore[type-abstract]

        # Get session resolver if available
        session_resolver: ISessionResolver | None = None
        with contextlib.suppress(Exception):
            session_resolver = provider.get_service(ISessionResolver)  # type: ignore[type-abstract]

        # Return request processor
        return RequestProcessor(
            command_proc, backend_proc, session_svc, response_proc, session_resolver
        )  # type: ignore[arg-type]

    # Register request processor and bind to interface
    _add_singleton(RequestProcessor, implementation_factory=_request_processor_factory)

    with contextlib.suppress(Exception):
        _add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )  # type: ignore[type-abstract]

    # Register streaming response processor service
    def _streaming_response_processor_factory(
        provider: IServiceProvider,
    ) -> StreamingResponseProcessorService:
        # Create streaming response processor service
        return StreamingResponseProcessorService()

    # Register streaming response processor service and bind to interface
    _add_singleton(
        StreamingResponseProcessorService,
        implementation_factory=_streaming_response_processor_factory,
    )

    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(type, IStreamingResponseProcessor),
            implementation_factory=_streaming_response_processor_factory,
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
