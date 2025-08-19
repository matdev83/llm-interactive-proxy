"""
Services and DI container configuration.

This module provides functions for configuring the DI container with services
and resolving services from the container.
"""

from __future__ import annotations

import contextlib
from typing import Any, Dict, List, Optional, Type, TypeVar, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection, ServiceProvider
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_handler_interface import (
    INonStreamingResponseHandler,
    IStreamingResponseHandler,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_service import BackendService
from src.core.services.command_processor import CommandProcessor
from src.core.services.command_service import CommandService
from src.core.services.app_settings_service import AppSettings
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.response_handlers import (
    DefaultNonStreamingResponseHandler,
    DefaultStreamingResponseHandler,
)
from src.core.services.response_processor import ResponseProcessor
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.services.session_service import SessionService

T = TypeVar("T")

# Global service collection
_service_collection: Optional[ServiceCollection] = None
_service_provider: Optional[ServiceProvider] = None


def get_service_collection() -> ServiceCollection:
    """Get the global service collection.

    Returns:
        The global service collection
    """
    global _service_collection
    if _service_collection is None:
        _service_collection = ServiceCollection()
    return _service_collection


def get_or_build_service_provider() -> ServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    Returns:
        The global service provider
    """
    global _service_provider
    if _service_provider is None:
        _service_provider = get_service_collection().build_service_provider()
    return _service_provider


def register_core_services(
    services: ServiceCollection, app_config: Optional[AppConfig] = None
) -> None:
    """Register core services with the service collection.

    Args:
        services: The service collection to register services with
        app_config: Optional application configuration
    """
    # Register AppConfig if provided
    if app_config is not None:
        services.add_instance(AppConfig, app_config)

    # Register session resolver
    services.add_singleton(DefaultSessionResolver)
    # Register both the concrete type and the interface
    services.add_singleton(ISessionResolver, DefaultSessionResolver)  # type: ignore

    # Register CommandRegistry
    from src.core.services.command_service import CommandRegistry
    services.add_singleton(CommandRegistry)
    
    # Register CommandService with factory
    def _command_service_factory(provider: ServiceProvider) -> CommandService:
        registry = provider.get_required_service(CommandRegistry)
        session_svc = provider.get_required_service(SessionService)
        return CommandService(registry, session_svc)
        
    # Register CommandService and bind to interface
    services.add_singleton(CommandService, implementation_factory=_command_service_factory)
    
    # Register ICommandService interface
    with contextlib.suppress(Exception):
        services.add_singleton(cast(Type, ICommandService), implementation_factory=_command_service_factory)
    
    # Register session service factory
    def _session_service_factory(provider: ServiceProvider) -> SessionService:
        # Import here to avoid circular imports
        from src.core.repositories.in_memory_session_repository import (
            InMemorySessionRepository,
        )

        # Create repository
        repository = InMemorySessionRepository()

        # Return session service
        return SessionService(repository)

    # Register session service and bind to interface
    services.add_singleton(
        SessionService, implementation_factory=_session_service_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, ISessionService),
            implementation_factory=_session_service_factory,
        )

    # Register command processor
    def _command_processor_factory(provider: ServiceProvider) -> CommandProcessor:
        # Get command service
        command_service = provider.get_required_service(ICommandService)  # type: ignore[type-abstract]
        
        # Return command processor
        return CommandProcessor(command_service)
        
    # Register command processor and bind to interface
    services.add_singleton(
        CommandProcessor, implementation_factory=_command_processor_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, ICommandProcessor),
            implementation_factory=_command_processor_factory,
        )
        
    # Register backend processor
    def _backend_processor_factory(provider: ServiceProvider) -> BackendProcessor:
        # Get backend service and session service
        backend_service = provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
        session_service = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        
        # Return backend processor
        return BackendProcessor(backend_service, session_service)
        
    # Register backend processor and bind to interface
    services.add_singleton(
        BackendProcessor, implementation_factory=_backend_processor_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, IBackendProcessor),
            implementation_factory=_backend_processor_factory,
        )
        
    # Register response handlers
    services.add_singleton(DefaultNonStreamingResponseHandler)
    services.add_singleton(DefaultStreamingResponseHandler)
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, INonStreamingResponseHandler),
            DefaultNonStreamingResponseHandler,
        )
        services.add_singleton(
            cast(Type, IStreamingResponseHandler),
            DefaultStreamingResponseHandler,
        )
        
    # Register response processor
    def _response_processor_factory(provider: ServiceProvider) -> ResponseProcessor:
        # Get response handlers
        non_streaming_handler = None
        streaming_handler = None
        try:
            non_streaming_handler = provider.get_service(INonStreamingResponseHandler)  # type: ignore[type-abstract]
            streaming_handler = provider.get_service(IStreamingResponseHandler)  # type: ignore[type-abstract]
        except Exception:
            pass
            
        # Create response processor
        return ResponseProcessor(non_streaming_handler, streaming_handler)
        
    # Register response processor and bind to interface
    services.add_singleton(
        ResponseProcessor, implementation_factory=_response_processor_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, IResponseProcessor),
            implementation_factory=_response_processor_factory,
        )
        
    # Register app settings
    def _app_settings_factory(provider: ServiceProvider) -> AppSettings:
        # Get app_state from FastAPI app if available
        app_state = None
        try:
            # Import here to avoid circular imports
            from fastapi import FastAPI
            
            # Get FastAPI app from app_config if available
            app_config = provider.get_service(AppConfig)
            if app_config and hasattr(app_config, "app") and isinstance(app_config.app, FastAPI):
                app_state = app_config.app.state
        except Exception:
            # Ignore errors, just log them at debug level
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Error getting app_state for AppSettings", exc_info=True)
            
        # Create app settings
        return AppSettings(app_state)
        
    # Register app settings and bind to interface
    services.add_singleton(
        AppSettings, implementation_factory=_app_settings_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, IAppSettings),
            implementation_factory=_app_settings_factory,
        )
        
    # Register backend service
    def _backend_service_factory(provider: ServiceProvider) -> BackendService:
        # Import required modules
        import httpx
        from src.core.services.backend_factory import BackendFactory
        from src.core.services.backend_registry import BackendRegistry, backend_registry
        from src.core.services.rate_limiter_service import RateLimiter
        
        # Get or create dependencies
        httpx_client = provider.get_service(httpx.AsyncClient)
        if httpx_client is None:
            httpx_client = httpx.AsyncClient()
            
        # Get app config
        app_config = provider.get_required_service(AppConfig)
        
        # Create backend factory
        backend_factory = BackendFactory(httpx_client, backend_registry)
        
        # Create rate limiter
        rate_limiter = RateLimiter()
        
        # Return backend service
        return BackendService(backend_factory, rate_limiter, app_config)
        
    # Register backend service and bind to interface
    services.add_singleton(
        BackendService, implementation_factory=_backend_service_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, IBackendService),
            implementation_factory=_backend_service_factory,
        )
        
    # Register request processor
    def _request_processor_factory(provider: ServiceProvider) -> RequestProcessor:
        # Get required services
        command_proc = provider.get_required_service(ICommandProcessor)  # type: ignore[type-abstract]
        backend_proc = provider.get_required_service(IBackendProcessor)  # type: ignore[type-abstract]
        session_svc = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        response_proc = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]
        
        # Get session resolver if available
        session_resolver = None
        try:
            session_resolver = provider.get_service(ISessionResolver)  # type: ignore[type-abstract]
        except Exception:
            pass
            
        # Return request processor
        return RequestProcessor(command_proc, backend_proc, session_svc, response_proc, session_resolver)  # type: ignore[arg-type]
        
    # Register request processor and bind to interface
    services.add_singleton(
        RequestProcessor, implementation_factory=_request_processor_factory
    )
    
    with contextlib.suppress(Exception):
        services.add_singleton(
            cast(Type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )


def get_service(service_type: Type[T]) -> Optional[T]:
    """Get a service from the global service provider.

    Args:
        service_type: The type of service to get

    Returns:
        The service instance, or None if the service is not registered
    """
    provider = get_or_build_service_provider()
    return provider.get_service(service_type)  # type: ignore


def get_required_service(service_type: Type[T]) -> T:
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