from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.core.commands.handler_factory import register_command_handlers
from src.core.common.logging import get_logger, setup_logging
from src.core.config.app_config import AppConfig, load_config
from src.core.di.services import get_service_collection
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.configuration import IConfig
from src.core.interfaces.loop_detector import ILoopDetector
from src.core.interfaces.rate_limiter import IRateLimiter
from src.core.interfaces.repositories import (
    IConfigRepository,
    ISessionRepository,
    IUsageRepository,
)
from src.core.interfaces.request_processor import IRequestProcessor
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService
from src.core.interfaces.usage_tracking import IUsageTrackingService
from src.core.repositories.in_memory_config_repository import InMemoryConfigRepository
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.repositories.in_memory_usage_repository import InMemoryUsageRepository
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService
from src.core.services.command_service import CommandRegistry, CommandService
from src.core.services.loop_detector import create_loop_detector
from src.core.services.rate_limiter import create_rate_limiter
from src.core.services.request_processor import RequestProcessor
from src.core.services.response_processor import ResponseProcessor
from src.core.services.session_service import SessionService
from src.core.services.usage_tracking_service import UsageTrackingService

logger = get_logger(__name__)


from typing import Any, Protocol

from src.core.interfaces.di import IServiceProvider


class IApplicationBuilder(Protocol):
    """Interface for application builders."""

    def build(self, config: AppConfig) -> FastAPI:
        """Build a FastAPI application.

        Args:
            config: The application configuration

        Returns:
            A configured FastAPI application
        """
        ...


class IServiceConfigurator(Protocol):
    """Interface for service configuration."""

    def configure_services(self, config: AppConfig) -> IServiceProvider:
        """Configure services for the application.

        Args:
            config: The application configuration

        Returns:
            A configured service provider
        """
        ...


class IMiddlewareConfigurator(Protocol):
    """Interface for middleware configuration."""

    def configure_middleware(self, app: FastAPI, config: AppConfig) -> None:
        """Configure middleware for the application.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        ...


class IRouteConfigurator(Protocol):
    """Interface for route configuration."""

    def configure_routes(self, app: FastAPI, provider: IServiceProvider) -> None:
        """Configure routes for the application.

        Args:
            app: The FastAPI application
            provider: The service provider
        """
        ...


class ServiceConfigurator:
    """Configures services for the application."""

    def configure_services(self, config: AppConfig) -> IServiceProvider:
        """Configure services for the application.

        Args:
            config: The application configuration

        Returns:
            A configured service provider
        """
        from src.core.interfaces.backend_service import IBackendService
        from src.core.interfaces.rate_limiter import IRateLimiter
        from src.core.services.command_service import CommandRegistry

        services = get_service_collection()

        # Register configuration
        services.add_instance(IConfig, config)

        # Register repositories
        # Type ignores are needed because mypy doesn't understand that these
        # concrete classes implement the abstract interfaces
        services.add_singleton(IConfigRepository, InMemoryConfigRepository)  # type: ignore
        services.add_singleton(ISessionRepository, InMemorySessionRepository)  # type: ignore
        services.add_singleton(IUsageRepository, InMemoryUsageRepository)  # type: ignore

        # Register core services
        # SessionService needs repository dependency, register with factory
        def session_service_factory(provider):
            session_repository = provider.get_required_service(ISessionRepository)
            return SessionService(session_repository)

        services.add_singleton_factory(ISessionService, session_service_factory)

        # CommandService needs dependencies, register with factory
        def command_service_factory(provider):
            command_registry = provider.get_required_service(CommandRegistry)
            session_service = provider.get_required_service(ISessionService)
            return CommandService(command_registry, session_service)

        services.add_singleton_factory(ICommandService, command_service_factory)

        # RequestProcessor needs dependencies - register as a factory
        def request_processor_factory(provider):
            from src.core.interfaces.command_service import ICommandService
            from src.core.interfaces.response_processor import IResponseProcessor
            from src.core.interfaces.session_service import ISessionService

            command_service = provider.get_required_service(ICommandService)
            backend_service = provider.get_required_service(IBackendService)
            session_service = provider.get_required_service(ISessionService)
            response_processor = provider.get_required_service(IResponseProcessor)
            return RequestProcessor(
                command_service, backend_service, session_service, response_processor
            )

        services.add_singleton_factory(IRequestProcessor, request_processor_factory)
        services.add_singleton(IResponseProcessor, ResponseProcessor)  # type: ignore
        services.add_singleton(IUsageTrackingService, UsageTrackingService)  # type: ignore

        # Register infrastructure services
        loop_detector = create_loop_detector()
        services.add_instance(ILoopDetector, loop_detector)  # type: ignore

        rate_limiter = create_rate_limiter(config)
        services.add_instance(IRateLimiter, rate_limiter)  # type: ignore

        # Register HTTP client
        client = httpx.AsyncClient(timeout=config.proxy_timeout)
        services.add_instance(httpx.AsyncClient, client)

        # Register command registry
        command_registry = CommandRegistry()
        services.add_instance(CommandRegistry, command_registry)

        # Register backend-related services with proper factory pattern
        self._register_backend_services(services, config)

        return services.build_service_provider()

    def _register_backend_services(self, services, config):
        """Register backend-related services.

        Args:
            services: The service collection
            config: The application configuration
        """

        # Register backend factory
        def backend_factory_factory(provider):
            httpx_client = provider.get_required_service(httpx.AsyncClient)
            return BackendFactory(httpx_client)

        services.add_singleton_factory(BackendFactory, backend_factory_factory)

        # Register backend service
        def backend_service_factory(provider):
            factory = provider.get_required_service(BackendFactory)
            rate_limiter = provider.get_required_service(IRateLimiter)
            config = provider.get_required_service(IConfig)
            return BackendService(factory, rate_limiter, config)

        services.add_singleton_factory(IBackendService, backend_service_factory)


class MiddlewareConfigurator:
    """Configures middleware for the application."""

    def configure_middleware(self, app: FastAPI, config: AppConfig) -> None:
        """Configure middleware for the application.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        from src.core.app.middleware_config import configure_middleware

        # Create a simplified config dict for middleware
        middleware_config = {
            "api_keys": config.auth.api_keys if config.auth else [],
            "disable_auth": config.auth.disable_auth if config.auth else False,
            "auth_token": (
                config.auth.auth_token
                if config.auth and hasattr(config.auth, "auth_token")
                else None
            ),
            "request_logging": (
                config.logging.request_logging
                if config.logging and hasattr(config.logging, "request_logging")
                else False
            ),
            "response_logging": (
                config.logging.response_logging
                if config.logging and hasattr(config.logging, "response_logging")
                else False
            ),
        }

        configure_middleware(app, middleware_config)


class RouteConfigurator:
    """Configures routes for the application."""

    def configure_routes(self, app: FastAPI, provider: IServiceProvider) -> None:
        """Configure routes for the application.

        Args:
            app: The FastAPI application
            provider: The service provider
        """
        # Store provider in app state for dependency injection
        app.state.service_provider = provider

        # Register main routes
        from src.core.app.controllers import register_routes

        register_routes(app)

        # Register models controller
        from src.core.app.controllers.models_controller import router as models_router

        app.include_router(models_router)

        # Register Anthropic router if needed
        from src.anthropic_router import router as anthropic_router

        app.include_router(anthropic_router)


class ApplicationBuilder:
    """Builds FastAPI applications with proper separation of concerns."""

    def __init__(
        self,
        service_configurator: IServiceConfigurator | None = None,
        middleware_configurator: IMiddlewareConfigurator | None = None,
        route_configurator: IRouteConfigurator | None = None,
    ):
        """Initialize the application builder.

        Args:
            service_configurator: Optional service configurator
            middleware_configurator: Optional middleware configurator
            route_configurator: Optional route configurator
        """
        self.service_configurator = service_configurator or ServiceConfigurator()
        self.middleware_configurator = (
            middleware_configurator or MiddlewareConfigurator()
        )
        self.route_configurator = route_configurator or RouteConfigurator()

    def build(self, config: AppConfig) -> FastAPI:
        """Build a FastAPI application.

        Args:
            config: The application configuration

        Returns:
            A configured FastAPI application
        """
        # Configure logging
        setup_logging(config)
        logger.info("Building application with improved factory")

        # Create FastAPI app with lifespan
        app = FastAPI(
            title="LLM Interactive Proxy",
            description="A proxy server that adds interactive features to LLM APIs",
            lifespan=self._create_lifespan(config),
        )

        # Store configuration
        app.state.app_config = config

        # Configure services
        service_provider = self.service_configurator.configure_services(config)
        app.state.service_provider = service_provider

        # Configure middleware
        self.middleware_configurator.configure_middleware(app, config)

        # Configure routes
        self.route_configurator.configure_routes(app, service_provider)

        # Configure error handlers
        from src.core.app.error_handlers import configure_exception_handlers

        configure_exception_handlers(app)

        # Set up backend configs for compatibility
        self._configure_backend_compatibility(app, config)

        logger.info("Application built successfully")
        return app

    def _create_lifespan(self, config: AppConfig):
        """Create lifespan context manager for the application.

        Args:
            config: The application configuration

        Returns:
            A lifespan context manager
        """

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Lifespan context manager for FastAPI application."""
            logger.info("Starting application")

            # Initialize HTTP client
            app.state.httpx_client = httpx.AsyncClient(timeout=config.proxy_timeout)

            # Register command handlers
            command_registry = app.state.service_provider.get_required_service(
                CommandRegistry
            )
            register_command_handlers(command_registry)

            yield

            # Clean up resources
            logger.info("Shutting down application")
            if hasattr(app.state, "httpx_client") and app.state.httpx_client:
                await app.state.httpx_client.aclose()

        return lifespan

    def _configure_backend_compatibility(self, app: FastAPI, config: AppConfig) -> None:
        """Configure backend compatibility settings.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        # Initialize compatibility state
        app.state.backend_configs = {}
        app.state.backends = {}
        app.state.failover_routes = config.failover_routes

        # Legacy config for middleware compatibility
        app.state.config = config

        # Initialize legacy backend instances for tests that expect them
        self._initialize_legacy_backends(app, config)

        # Add chat_completions_func for Anthropic router compatibility
        self._add_chat_completions_func(app)

    def _initialize_legacy_backends(self, app: FastAPI, config: AppConfig) -> None:
        """Initialize legacy backend instances for compatibility.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        # Import backend classes
        from src.connectors.anthropic import AnthropicBackend
        from src.connectors.gemini import GeminiBackend
        from src.connectors.openai import OpenAIConnector
        from src.connectors.openrouter import OpenRouterBackend
        from src.connectors.zai import ZAIConnector

        # Get HTTP client from app state
        httpx_client = getattr(app.state, "httpx_client", None)
        if httpx_client is None:
            httpx_client = httpx.AsyncClient(timeout=config.proxy_timeout)
            app.state.httpx_client = httpx_client

        # Initialize backend instances
        app.state.openrouter_backend = OpenRouterBackend(httpx_client)
        app.state.gemini_backend = GeminiBackend(httpx_client)
        app.state.openai_backend = OpenAIConnector(httpx_client)
        app.state.anthropic_backend = AnthropicBackend(httpx_client)
        app.state.zai_backend = ZAIConnector(httpx_client)

        # Set up API keys if available
        if config.backends.openrouter:
            app.state.openrouter_backend.api_keys = (
                [config.backends.openrouter.api_key]
                if config.backends.openrouter.api_key
                else []
            )

        if config.backends.gemini:
            app.state.gemini_backend.api_keys = (
                [config.backends.gemini.api_key]
                if config.backends.gemini.api_key
                else []
            )

        if config.backends.openai:
            app.state.openai_backend.api_keys = (
                [config.backends.openai.api_key]
                if config.backends.openai.api_key
                else []
            )

        if config.backends.anthropic:
            app.state.anthropic_backend.api_keys = (
                [config.backends.anthropic.api_key]
                if config.backends.anthropic.api_key
                else []
            )

        if config.backends.zai:
            app.state.zai_backend.api_keys = (
                [config.backends.zai.api_key] if config.backends.zai.api_key else []
            )

        logger.debug("Legacy backend instances initialized")

    def _add_chat_completions_func(self, app: FastAPI) -> None:
        """Add chat_completions_func for Anthropic router compatibility.

        Args:
            app: The FastAPI application
        """

        async def chat_completions_wrapper(request_data, http_request):
            """Wrapper function for chat completions that uses the new architecture."""
            from src.core.interfaces.request_processor import IRequestProcessor

            if hasattr(app.state, "service_provider") and app.state.service_provider:
                request_processor = app.state.service_provider.get_required_service(
                    IRequestProcessor
                )
                return await request_processor.process_request(
                    http_request, request_data
                )
            else:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=500, detail="Service provider not available"
                )

        app.state.chat_completions_func = chat_completions_wrapper


def build_app(
    config: AppConfig | dict | None = None,  # Allow dict for flexibility, will convert
) -> FastAPI:
    """Build a FastAPI application using the improved factory.

    This is a compatibility wrapper for the new application builder.

    Args:
        config: Optional AppConfig object or dictionary to use. If None, configuration will be loaded.

    Returns:
        A configured FastAPI application
    """

    # Load configuration if not provided, or convert dict to AppConfig
    if config is None:
        app_config = load_config()
    elif isinstance(config, dict):
        app_config = AppConfig(**config)
    elif isinstance(config, AppConfig):
        app_config = config
    else:
        raise TypeError(
            f"Unsupported config type: {type(config)}. Expected AppConfig, dict, or None."
        )

    # Handle test environment setup (ensures it's always applied if config is provided or loaded)
    _setup_test_environment(app_config)

    # Build application using the improved builder
    builder = ApplicationBuilder()
    return builder.build(app_config)  # Pass the AppConfig object


def register_services(services: dict[str, Any], app: FastAPI) -> None:
    """Register services with the application for backward compatibility.

    Args:
        services: Dictionary of services to register
        app: The FastAPI application
    """
    # This is a compatibility function for legacy code that expects register_services
    # In the new architecture, services are registered through the DI container
    # We'll just ensure the app has a service_provider
    if not hasattr(app.state, "service_provider"):
        from src.core.di.services import get_service_provider

        app.state.service_provider = get_service_provider()


def _setup_test_environment(config: AppConfig) -> None:
    """Set up test environment if running under pytest.

    Args:
        config: The application configuration
    """
    import os

    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and hasattr(config, "auth")
        and hasattr(config.auth, "api_keys")
        and not config.auth.api_keys
    ):
        config.auth.api_keys = ["test-proxy-key"]
