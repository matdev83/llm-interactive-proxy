from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from starlette.responses import Response

from src.core.commands.handler_factory import register_command_handlers
from src.core.common.logging import get_logger, setup_logging
from src.core.config.app_config import AppConfig, load_config
from src.core.config.config_loader import get_openrouter_headers
from src.core.di.services import get_service_collection
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.configuration import IConfig
from src.core.interfaces.di import IServiceCollection
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


from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol, cast

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

        services: IServiceCollection = get_service_collection()  # type: ignore

        # Register configuration
        services.add_instance(IConfig, config)  # type: ignore[type-abstract]

        # Register repositories
        # Type ignores are needed because mypy doesn't understand that these
        # concrete classes implement the abstract interfaces
        services.add_singleton(IConfigRepository, InMemoryConfigRepository)  # type: ignore[type-abstract]
        services.add_singleton(ISessionRepository, InMemorySessionRepository)  # type: ignore[type-abstract]
        services.add_singleton(IUsageRepository, InMemoryUsageRepository)  # type: ignore[type-abstract]

        # Register core services
        # SessionService needs repository dependency, register with factory
        def session_service_factory(provider: IServiceProvider) -> SessionService:
            session_repository: ISessionRepository = provider.get_required_service(
                ISessionRepository
            )
            return SessionService(session_repository)

        services.add_singleton_factory(
            ISessionService, session_service_factory
        )  # type: ignore[type-abstract]

        # CommandService needs dependencies, register with factory
        def command_service_factory(provider: IServiceProvider) -> CommandService:
            command_registry: CommandRegistry = provider.get_required_service(
                CommandRegistry
            )
            session_service: ISessionService = provider.get_required_service(
                ISessionService
            )
            return CommandService(command_registry, session_service)

        services.add_singleton_factory(
            ICommandService, command_service_factory
        )  # type: ignore[type-abstract]

        # RequestProcessor needs dependencies - register as a factory
        def request_processor_factory(provider: IServiceProvider) -> RequestProcessor:
            from src.core.interfaces.command_service import ICommandService
            from src.core.interfaces.response_processor import IResponseProcessor
            from src.core.interfaces.session_service import ISessionService

            command_service: ICommandService = provider.get_required_service(
                ICommandService
            )
            backend_service: IBackendService = provider.get_required_service(
                IBackendService
            )
            session_service = provider.get_required_service(ISessionService)
            response_processor: IResponseProcessor = provider.get_required_service(
                IResponseProcessor
            )
            return RequestProcessor(
                command_service, backend_service, session_service, response_processor
            )

        services.add_singleton_factory(
            IRequestProcessor, request_processor_factory
        )  # type: ignore[type-abstract]

        # ResponseProcessor needs loop detector - register as a factory
        def response_processor_factory(provider: IServiceProvider) -> ResponseProcessor:
            from src.core.interfaces.loop_detector import ILoopDetector

            loop_detector = provider.get_service(ILoopDetector)
            return ResponseProcessor(loop_detector=loop_detector)

        services.add_singleton_factory(
            IResponseProcessor, response_processor_factory
        )  # type: ignore[type-abstract]
        services.add_singleton(IUsageTrackingService, UsageTrackingService)  # type: ignore[type-abstract]

        # Register infrastructure services
        loop_detector = create_loop_detector()
        services.add_instance(ILoopDetector, loop_detector)  # type: ignore[type-abstract]

        rate_limiter = create_rate_limiter(config)
        services.add_instance(IRateLimiter, rate_limiter)  # type: ignore[type-abstract]

        # Register HTTP client
        client: httpx.AsyncClient = httpx.AsyncClient(timeout=config.proxy_timeout)
        services.add_instance(httpx.AsyncClient, client)

        # Register command registry
        command_registry = CommandRegistry()  # type: ignore[no-untyped-call]
        services.add_instance(CommandRegistry, command_registry)

        # Register backend-related services with proper factory pattern
        self._register_backend_services(services, config)

        return services.build_service_provider()

    def _register_backend_services(
        self, services: IServiceCollection, config: AppConfig
    ) -> None:
        """Register backend-related services.

        Args:
            services: The service collection
            config: The application configuration
        """

        # Register backend factory
        def backend_factory_factory(provider: IServiceProvider) -> BackendFactory:
            httpx_client: httpx.AsyncClient = provider.get_required_service(
                httpx.AsyncClient
            )
            return BackendFactory(httpx_client)

        services.add_singleton_factory(BackendFactory, backend_factory_factory)

        # Register backend service
        def backend_service_factory(provider: IServiceProvider) -> BackendService:
            factory = provider.get_required_service(BackendFactory)
            rate_limiter = provider.get_required_service(IRateLimiter)
            config: AppConfig = provider.get_required_service(IConfig)  # type: ignore
            # Convert backend configs to dict if it's a pydantic model
            backend_configs = (
                config.backends.model_dump()
                if hasattr(config.backends, "model_dump")
                else {}
            )
            return BackendService(
                factory,
                rate_limiter,
                cast(IConfig, config),
                backend_configs=backend_configs,
            )

        services.add_singleton_factory(
            IBackendService, backend_service_factory
        )  # type: ignore[type-abstract]


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
        middleware_config: dict[str, Any] = {
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
        app: FastAPI = FastAPI(
            title="LLM Interactive Proxy",
            description="A proxy server that adds interactive features to LLM APIs",
            lifespan=self._create_lifespan(config),
        )

        # Store configuration
        app.state.app_config = config

        # Configure services
        service_provider: IServiceProvider = (
            self.service_configurator.configure_services(config)
        )
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

        # Initialize session manager for legacy code compatibility
        from src.core.interfaces.session_service import ISessionService
        from src.core.services.sync_session_manager import SyncSessionManager

        session_service: ISessionService = service_provider.get_required_service(
            ISessionService
        )  # type: ignore[type-abstract]
        app.state.session_manager = SyncSessionManager(session_service)

        logger.info("Application built successfully")
        return app

    def _create_lifespan(
        self, config: AppConfig
    ) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
        """Create lifespan context manager for the application.

        Args:
            config: The application configuration

        Returns:
            A lifespan context manager
        """
        builder = self  # Capture self reference for use in nested function

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            """Lifespan context manager for FastAPI application."""
            logger.info("Starting application")

            # Initialize HTTP client
            app.state.httpx_client = httpx.AsyncClient(timeout=config.proxy_timeout)

            # Register command handlers
            command_registry: CommandRegistry = (
                app.state.service_provider.get_required_service(CommandRegistry)
            )
            register_command_handlers(command_registry)

            # Initialize legacy backend instances for tests that expect them
            await builder._initialize_legacy_backends(app, config)

            # Initialize loop detection middleware if enabled
            await builder._initialize_loop_detection_middleware(app, config)

            # Register middleware components with the response processor
            await builder._register_middleware_components(app)

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

        # Store the app config in app state
        app.state.app_config = config

        # Add chat_completions_func for Anthropic router compatibility
        self._add_chat_completions_func(app)

    async def _initialize_legacy_backends(
        self, app: FastAPI, config: AppConfig
    ) -> None:
        """Initialize backend instances and attach them to app.state for legacy compatibility."""
        logger.info("Initializing legacy backends and state attributes...")
        backend_factory: BackendFactory = (
            app.state.service_provider.get_required_service(BackendFactory)
        )

        # Initialize functional_backends set
        app.state.functional_backends = set()

        # Set default backend_type
        app.state.backend_type = config.backends.default_backend

        # Initialize Anthropic backend
        if config.backends.anthropic and config.backends.anthropic.api_key:
            logger.debug("Initializing legacy backend: anthropic")
            backend_instance: Any = backend_factory.create_backend("anthropic")

            init_kwargs: dict[str, Any] = {
                "anthropic_api_base_url": config.backends.anthropic.api_url,
                "key_name": "anthropic",
                "api_key": config.backends.anthropic.api_key[0],
            }

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.anthropic_backend = backend_instance
            app.state.functional_backends.add("anthropic")
            logger.info(
                "Initialized legacy backend 'anthropic' and attached to app.state"
            )

        # Initialize OpenRouter backend
        if config.backends.openrouter and config.backends.openrouter.api_key:
            logger.debug("Initializing legacy backend: openrouter")
            backend_instance = backend_factory.create_backend("openrouter")

            init_kwargs = {
                "openrouter_api_base_url": config.backends.openrouter.api_url,
                "key_name": "openrouter",
                "api_key": config.backends.openrouter.api_key[0],
            }
            # Add headers provider as a separate kwarg if needed
            init_kwargs["openrouter_headers_provider"] = (
                lambda key_name, api_key: get_openrouter_headers(
                    config.to_legacy_config(), api_key
                )
            )

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.openrouter_backend = backend_instance
            # Register legacy instance in the BackendService cache so code that
            # resolves backends from the service uses the same instance (tests
            # patch `app.state.openrouter_backend.chat_completions`).
            try:
                backend_service: IBackendService = (
                    app.state.service_provider.get_required_service(IBackendService)
                )
                # Make best-effort assignment
                backend_service._backends["openrouter"] = backend_instance
            except Exception:
                # If DI not ready or shape differs, skip silently
                pass
            app.state.functional_backends.add("openrouter")
            logger.info(
                "Initialized legacy backend 'openrouter' and attached to app.state"
            )

        # Initialize Gemini backend
        if config.backends.gemini and config.backends.gemini.api_key:
            logger.debug("Initializing legacy backend: gemini")
            backend_instance = backend_factory.create_backend("gemini")

            init_kwargs = {
                "gemini_api_base_url": config.backends.gemini.api_url
                or "https://generativelanguage.googleapis.com",
                "key_name": "gemini",
                "api_key": config.backends.gemini.api_key[0],
            }

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.gemini_backend = backend_instance
            try:
                backend_service: IBackendService = (
                    app.state.service_provider.get_required_service(IBackendService)
                )
                backend_service._backends["gemini"] = backend_instance
            except Exception:
                pass
            app.state.functional_backends.add("gemini")
            logger.info("Initialized legacy backend 'gemini' and attached to app.state")

        # Initialize OpenAI backend
        if config.backends.openai and config.backends.openai.api_key:
            logger.debug("Initializing legacy backend: openai")
            backend_instance = backend_factory.create_backend("openai")

            init_kwargs = {
                "openai_api_base_url": config.backends.openai.api_url
                or "https://api.openai.com/v1",
                "key_name": "openai",
                "api_key": config.backends.openai.api_key[0],
            }

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.openai_backend = backend_instance
            try:
                backend_service: IBackendService = (
                    app.state.service_provider.get_required_service(IBackendService)
                )
                backend_service._backends["openai"] = backend_instance
            except Exception:
                pass
            app.state.functional_backends.add("openai")
            logger.info("Initialized legacy backend 'openai' and attached to app.state")

        # Initialize ZAI backend
        if config.backends.zai and config.backends.zai.api_key:
            logger.debug("Initializing legacy backend: zai")
            backend_instance = backend_factory.create_backend("zai")

            init_kwargs = {
                "zai_api_base_url": config.backends.zai.api_url,
                "key_name": "zai",
                "api_key": config.backends.zai.api_key[0],
            }

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.zai_backend = backend_instance
            try:
                backend_service: IBackendService = (
                    app.state.service_provider.get_required_service(IBackendService)
                )
                backend_service._backends["zai"] = backend_instance
            except Exception:
                pass
            app.state.functional_backends.add("zai")
            logger.info("Initialized legacy backend 'zai' and attached to app.state")

        # Initialize Qwen OAuth backend
        if config.backends.qwen_oauth and config.backends.qwen_oauth.api_key:
            logger.debug("Initializing legacy backend: qwen_oauth")
            backend_instance = backend_factory.create_backend("qwen_oauth")

            init_kwargs = {
                "qwen_oauth_api_base_url": config.backends.qwen_oauth.api_url,
                "key_name": "qwen_oauth",
                "api_key": config.backends.qwen_oauth.api_key[0],
            }

            await backend_factory.initialize_backend(backend_instance, init_kwargs)
            app.state.qwen_oauth_backend = backend_instance
            try:
                backend_service: IBackendService = (
                    app.state.service_provider.get_required_service(IBackendService)
                )
                backend_service._backends["qwen_oauth"] = backend_instance
            except Exception:
                pass
            app.state.functional_backends.add("qwen_oauth")
            logger.info(
                "Initialized legacy backend 'qwen_oauth' and attached to app.state"
            )

        # Initialize other legacy state attributes needed by tests
        app.state.force_set_project = getattr(
            config.session, "force_set_project", False
        )

        # Initialize additional compatibility attributes
        app.state.config = config.to_legacy_config()  # Legacy config dict format
        app.state.default_interactive_mode = config.session.default_interactive_mode
        app.state.disable_interactive_commands = (
            config.session.disable_interactive_commands
        )
        app.state.command_prefix = config.command_prefix

        logger.info(
            f"Initialized {len(app.state.functional_backends)} functional backends: {app.state.functional_backends}"
        )

    def _add_chat_completions_func(self, app: FastAPI) -> None:
        """Add chat_completions_func for Anthropic router compatibility.

        Args:
            app: The FastAPI application
        """

        async def chat_completions_wrapper(
            request_data: Any, http_request: Request
        ) -> Response:
            """Wrapper function for chat completions that uses the new architecture."""
            from src.core.interfaces.request_processor import IRequestProcessor

            if hasattr(app.state, "service_provider") and app.state.service_provider:
                request_processor: IRequestProcessor = (
                    app.state.service_provider.get_required_service(IRequestProcessor)
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

    async def _initialize_loop_detection_middleware(
        self, app: FastAPI, config: AppConfig
    ) -> None:
        """Initialize loop detection middleware based on configuration.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        from src.loop_detection.config import LoopDetectionConfig
        from src.response_middleware import configure_loop_detection_middleware

        # Check if loop detection is enabled via environment or config
        loop_detection_enabled: bool = (
            os.environ.get("LOOP_DETECTION_ENABLED", "false").lower() == "true"
        )

        if loop_detection_enabled:
            # Create loop detection config from environment
            loop_config: LoopDetectionConfig = LoopDetectionConfig(
                enabled=True,
                buffer_size=int(os.environ.get("LOOP_DETECTION_BUFFER_SIZE", "8192")),
                max_pattern_length=int(
                    os.environ.get("LOOP_DETECTION_MAX_PATTERN_LENGTH", "1000")
                ),
            )

            # Configure the global loop detection middleware
            configure_loop_detection_middleware(loop_config)
            logger.info(
                f"Initialized loop detection middleware with config: buffer_size={loop_config.buffer_size}, max_pattern_length={loop_config.max_pattern_length}"
            )
        else:
            # Explicitly configure with disabled config to clear any existing processors
            loop_config = LoopDetectionConfig(enabled=False)
            configure_loop_detection_middleware(loop_config)
            logger.info("Loop detection middleware is disabled")

    async def _register_middleware_components(self, app: FastAPI) -> None:
        """Register middleware components with the response processor.

        Args:
            app: The FastAPI application
        """
        if not hasattr(app.state, "service_provider"):
            logger.warning(
                "Service provider not available, skipping middleware registration"
            )
            return

        # Get the response processor from the service provider
        try:
            from src.core.interfaces.response_processor import IResponseProcessor
            from src.core.services.tool_call_loop_middleware import (
                ToolCallLoopDetectionMiddleware,
            )

            response_processor: IResponseProcessor = (
                app.state.service_provider.get_required_service(IResponseProcessor)
            )

            # Create and register tool call loop detection middleware
            tool_call_middleware: ToolCallLoopDetectionMiddleware = (
                ToolCallLoopDetectionMiddleware()  # type: ignore[no-untyped-call]
            )
            await response_processor.register_middleware(
                tool_call_middleware, priority=10
            )

            # Store middleware for access in tests
            app.state.tool_call_loop_middleware = tool_call_middleware

            logger.info("Registered tool call loop detection middleware")
        except Exception as e:
            logger.error(
                f"Failed to register middleware components: {e}", exc_info=True
            )

    @classmethod
    def _setup_test_environment(cls, config: AppConfig) -> None:
        """Set up test environment if running under pytest.

        Args:
            config: The application configuration
        """
        from src.core.config.app_config import BackendConfig

        if os.environ.get("PYTEST_CURRENT_TEST"):
            # Only add test auth keys if auth is enabled and keys are missing
            if (
                hasattr(config, "auth")
                and not config.auth.disable_auth
                and not config.auth.api_keys
            ):
                config.auth.api_keys = ["test-proxy-key"]

            # Ensure backend configurations have dummy API keys for initialization
            if hasattr(config, "backends"):
                if (
                    not hasattr(config.backends, "openrouter")
                    or not config.backends.openrouter
                ):
                    config.backends.openrouter = BackendConfig(
                        api_key=["test-key-openrouter"]
                    )
                elif not config.backends.openrouter.api_key:
                    config.backends.openrouter.api_key = ["test-key-openrouter"]

                if not hasattr(config.backends, "gemini") or not config.backends.gemini:
                    config.backends.gemini = BackendConfig(api_key=["test-key-gemini"])
                elif not config.backends.gemini.api_key:
                    config.backends.gemini.api_key = ["test-key-gemini"]

                if (
                    not hasattr(config.backends, "anthropic")
                    or not config.backends.anthropic
                ):
                    config.backends.anthropic = BackendConfig(
                        api_key=["test-key-anthropic"]
                    )
                elif not config.backends.anthropic.api_key:
                    config.backends.anthropic.api_key = ["test-key-anthropic"]


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
        app_config: AppConfig = load_config()
    elif isinstance(config, dict):
        app_config = AppConfig(**config)
    elif isinstance(config, AppConfig):
        app_config = config
    else:
        raise TypeError(
            f"Unsupported config type: {type(config)}. Expected AppConfig, dict, or None."
        )

    # Handle test environment setup (ensures it's always applied if config is provided or loaded)
    ApplicationBuilder._setup_test_environment(app_config)

    # Build application using the improved builder
    builder: ApplicationBuilder = ApplicationBuilder()
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
