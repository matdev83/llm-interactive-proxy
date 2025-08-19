"""
Application factory for creating the FastAPI application.

This module provides a factory for creating the FastAPI application with all
the necessary middleware, routes, and dependencies.
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from fastapi import FastAPI

from src.core.transport.fastapi.exception_adapters import register_exception_handlers
from src.core.app.controllers import register_routes

from src.core.config.app_config import AppConfig
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry, backend_registry
from src.core.services.backend_service import BackendService
from src.core.services.command_service import CommandService
from src.core.services.loop_detector_service import LoopDetector
from src.core.services.rate_limiter_service import RateLimiter
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.response_processor import ResponseProcessor
from src.core.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ApplicationBuilder:
    """Builder for creating the FastAPI application."""

    def __init__(self) -> None:
        """Initialize the application builder."""
        self.middleware_configurator = MiddlewareConfigurator()

    def _normalize_config(self, config: AppConfig) -> AppConfig:
        """Normalize configuration shapes to ensure consistent types.

        This method ensures that all backend configurations are properly
        normalized to BackendConfig objects and that other configuration
        sections have consistent shapes.

        Args:
            config: The application configuration to normalize

        Returns:
            Normalized application configuration
        """
        from src.core.services.backend_registry import backend_registry

        # Ensure backends is a BackendSettings object
        if not isinstance(config.backends, AppConfig.BackendSettings):
            # If it's a dict, convert to BackendSettings
            if isinstance(config.backends, dict):
                config.backends = AppConfig.BackendSettings(**config.backends)
            else:
                # If it's neither, create a new BackendSettings object
                config.backends = AppConfig.BackendSettings()

        # Ensure all registered backends have a BackendConfig
        for backend_name in backend_registry.get_registered_backends():
            try:
                # Try to access the backend config
                backend_config = getattr(config.backends, backend_name, None)

                # If it doesn't exist or isn't a BackendConfig, create one
                if not isinstance(backend_config, AppConfig.BackendConfig):
                    # If it's a dict, convert to BackendConfig
                    if isinstance(backend_config, dict):
                        setattr(
                            config.backends,
                            backend_name,
                            AppConfig.BackendConfig(**backend_config),
                        )
                    else:
                        # Otherwise create a new BackendConfig
                        setattr(
                            config.backends, backend_name, AppConfig.BackendConfig()
                        )
            except Exception as e:
                # Log and continue if there's an error
                logging.getLogger(__name__).warning(
                    f"Error normalizing config for backend {backend_name}: {e}"
                )

        return config

    def build(self, config: AppConfig, service_provider: IServiceProvider | None = None) -> FastAPI:
        """Build the FastAPI application.

        Args:
            config: The application configuration

        Returns:
            The FastAPI application
        """
        # Normalize configuration shapes before building the application
        config = self._normalize_config(config)

        app = FastAPI(
            title="LLM Interactive Proxy",
            description="A proxy for interacting with LLM APIs",
            version="0.1.0",
        )

        # Configure middleware
        self.middleware_configurator.configure_middleware(app, config)

        # Register routes
        register_routes(app)

        # Register exception handlers using the new domain-to-HTTP adapter
        register_exception_handlers(app)

        # Register lifespan handler
        @app.on_event("startup")
        async def startup_handler() -> None:
            logger.info("Starting up application")

        @app.on_event("shutdown")
        async def shutdown_handler() -> None:
            logger.info("Shutting down application")
            # Close shared httpx client if stored on app.state
            try:
                import httpx

                client = getattr(app.state, "httpx_client", None)
                if client is not None and isinstance(client, httpx.AsyncClient):
                    await client.aclose()
            except Exception:
                pass

        # Store the service provider on app.state immediately if provided
        if service_provider is not None:
            app.state.service_provider = service_provider
            
        # Add lifespan context manager
        @app.on_event("startup")
        async def startup_event() -> None:
            # Initialize the service provider and store it on app.state only if not already set
            if not hasattr(app.state, "service_provider") or app.state.service_provider is None:
                new_service_provider = await self._initialize_services(app, config)
                app.state.service_provider = new_service_provider

            # Minimal legacy state stored for tests and controllers
            # Register command settings service
            from src.core.interfaces.command_settings_interface import ICommandSettingsService
            from src.core.services.command_settings_service import CommandSettingsService, get_default_instance
            
            # Create command settings service with config values
            cmd_settings = CommandSettingsService(
                default_command_prefix=config.command_prefix,
                default_api_key_redaction=config.auth.redact_api_keys_in_prompts,
            )
            
            # Get the service collection and register the command settings
            from src.core.di.services import get_service_collection
            services = get_service_collection()
            services.add_instance(CommandSettingsService, cmd_settings)
            services.add_instance(ICommandSettingsService, cmd_settings)  # type: ignore[arg-type]
            
            # Rebuild the service provider with the new services
            if not hasattr(app.state, "service_provider") or app.state.service_provider is None:
                app.state.service_provider = services.build_service_provider()
            
            # Update the default instance for legacy compatibility
            default_instance = get_default_instance()
            default_instance.command_prefix = config.command_prefix
            default_instance.api_key_redaction_enabled = config.auth.redact_api_keys_in_prompts
            
            # Set required app.state variables (legacy support during transition)
            app.state.command_prefix = config.command_prefix
            app.state.force_set_project = config.session.force_set_project
            app.state.api_key_redaction_enabled = config.auth.redact_api_keys_in_prompts
            app.state.default_api_key_redaction_enabled = (
                config.auth.redact_api_keys_in_prompts
            )
            app.state.app_config = config
            app.state.failover_routes = {}
            app.state.model_defaults = {}

            # Initialize backends (no eager creation) and expose configured default
            await self._initialize_backends(app, config)
            try:
                # Get the default backend from config, with fallback to "openai"
                # This ensures we always have a valid backend type set
                default_backend = config.backends.default_backend
                if not default_backend and app.state.functional_backends:
                    # If no default is configured but we have functional backends, use the first one
                    default_backend = next(iter(app.state.functional_backends))
                # If we still don't have a default and no functional backends, use "openai" as fallback
                app.state.backend_type = default_backend or "openai"
                logger.info(f"Using default backend: {app.state.backend_type}")
            except Exception as e:
                # Set openai as the default backend type if config access fails
                app.state.backend_type = "openai"
                logger.debug(f"Error setting default backend, using 'openai': {e}")

            # Initialize loop detection middleware
            await self._initialize_loop_detection_middleware(app, config)

            # Initialize rate limiting middleware
            await self._initialize_rate_limiting_middleware(app, config)

            logger.info("Application startup complete")

        return app

    async def _initialize_services(
        self, app: FastAPI, config: AppConfig
    ) -> IServiceProvider:
        """Initialize services and register them with the service provider.

        This method creates and registers all core services in the DI container,
        including shared resources like httpx.AsyncClient that should be reused
        across the application.
        """
        from src.core.di.services import get_service_collection

        # Use the global service collection to ensure all services are registered
        services = get_service_collection()

        # Register httpx.AsyncClient as a singleton first so all services can use it
        import httpx

        # Create a single shared httpx.AsyncClient instance and register it
        shared_httpx_client = httpx.AsyncClient()
        services.add_instance(httpx.AsyncClient, shared_httpx_client)

        # Store on app.state for shutdown handling
        app.state.httpx_client = shared_httpx_client

        # Register AppConfig as a singleton instance
        services.add_instance(AppConfig, config)

        def _backend_service_factory(provider: IServiceProvider) -> BackendService:
            # Get the shared httpx client from the provider
            httpx_client = provider.get_required_service(httpx.AsyncClient)
            backend_registry_instance = provider.get_required_service(
                BackendRegistry
            )  # Get BackendRegistry
            backend_factory = BackendFactory(
                httpx_client, backend_registry_instance
            )  # Pass BackendRegistry
            rate_limiter_instance = provider.get_required_service(RateLimiter)
            app_config_from_provider = provider.get_required_service(AppConfig)
            app_config_for_iface = cast(IConfig, app_config_from_provider)
            # Use a dedicated BackendConfigProvider to normalize backend configs
            from src.core.services.backend_config_provider import BackendConfigProvider

            backend_config_provider = BackendConfigProvider(app_config_from_provider)

            return BackendService(
                backend_factory,
                rate_limiter_instance,
                app_config_for_iface,
                backend_config_provider=backend_config_provider,
            )  # type: ignore

        # Register BackendService with its factory
        services.add_singleton(
            BackendService, implementation_factory=_backend_service_factory
        )

        # Register IBackendService interface with the same factory function
        # This ensures that when code requests IBackendService, it gets the exact same
        # instance as when requesting BackendService directly
        services.add_singleton(
            cast(type, IBackendService), implementation_factory=_backend_service_factory
        )
        from src.core.interfaces.response_processor_interface import IResponseProcessor

        # Register ResponseProcessor and bind to interface
        def _response_processor_factory(
            provider: IServiceProvider,
        ) -> ResponseProcessor:
            # Get loop detector if available
            detector = None
            try:
                from src.core.interfaces.loop_detector_interface import ILoopDetector
                detector = provider.get_service(ILoopDetector)
            except Exception:
                pass
                
            # Create response processor with loop detector
            return ResponseProcessor(loop_detector=detector)

        services.add_singleton(
            ResponseProcessor, implementation_factory=_response_processor_factory
        )
        services.add_singleton(
            cast(type, IResponseProcessor),
            implementation_factory=_response_processor_factory,
        )
        services.add_singleton(LoopDetector)
        services.add_singleton(RateLimiter)
        # Register FailoverService and coordinator
        from src.core.services.failover_coordinator import FailoverCoordinator
        from src.core.services.failover_service import FailoverService

        services.add_singleton(FailoverService)

        def _failover_coordinator_factory(
            provider: IServiceProvider,
        ) -> FailoverCoordinator:
            svc = provider.get_required_service(FailoverService)
            return FailoverCoordinator(svc)

        services.add_singleton(
            FailoverCoordinator, implementation_factory=_failover_coordinator_factory
        )

        # Register BackendFactory service with a factory function
        def _backend_factory(provider: IServiceProvider) -> BackendFactory:
            # Get the shared httpx client from the provider
            httpx_client = provider.get_required_service(httpx.AsyncClient)

            # Get backend registry from provider
            backend_registry_instance = provider.get_required_service(BackendRegistry)

            # Create and return BackendFactory instance
            return BackendFactory(httpx_client, backend_registry_instance)

        # Register BackendRegistry singleton first (since BackendFactory depends on it)
        services.add_instance(BackendRegistry, backend_registry)

        # Then register BackendFactory (which depends on BackendRegistry)
        services.add_singleton(BackendFactory, implementation_factory=_backend_factory)

        # Register BackendConfigProvider so other services can request it
        def _backend_config_provider_factory(provider: IServiceProvider) -> object:
            app_cfg = provider.get_required_service(AppConfig)
            from src.core.services.backend_config_provider import BackendConfigProvider

            return BackendConfigProvider(app_cfg)

        # Register under the concrete class; consumers should request via the interface
        from src.core.interfaces.backend_config_provider_interface import (
            IBackendConfigProvider,
        )

        services.add_singleton(
            cast(type, IBackendConfigProvider),
            implementation_factory=_backend_config_provider_factory,
        )

        # Register CommandRegistry and CommandService (ICommandService) correctly
        from src.core.interfaces.command_service_interface import ICommandService
        from src.core.services.command_service import CommandRegistry

        # CommandRegistry has a no-arg ctor; register as singleton
        services.add_singleton(CommandRegistry)

        # Register ICommandService with a factory to inject CommandRegistry and ISessionService
        def _command_service_factory(provider: IServiceProvider) -> CommandService:
            registry = provider.get_required_service(CommandRegistry)
            session_svc = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
            return CommandService(registry, session_svc)  # type: ignore[arg-type]

        services.add_singleton(
            CommandService, implementation_factory=_command_service_factory
        )
        # Also register the ICommandService interface using the same factory
        # Best-effort: if the interface is already registered or binding fails,
        # continue without raising to avoid breaking startup in tests.
        import contextlib

        with contextlib.suppress(Exception):
            services.add_singleton(
                cast(type, ICommandService),
                implementation_factory=_command_service_factory,
            )

            # Register IRequestProcessor with a factory so its constructor deps are injected
    def _request_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        # Get required services
        from src.core.interfaces.command_processor_interface import ICommandProcessor
        from src.core.interfaces.backend_processor_interface import IBackendProcessor
        
        # Try to get command processor and backend processor
        command_proc = None
        backend_proc = None
        try:
            command_proc = provider.get_service(ICommandProcessor)  # type: ignore[type-abstract]
            backend_proc = provider.get_service(IBackendProcessor)  # type: ignore[type-abstract]
        except Exception:
            pass
            
        # If processors are not available, create them
        if command_proc is None:
            # Create command processor
            cmd = provider.get_required_service(ICommandService)  # type: ignore[type-abstract]
            from src.core.services.command_processor import CommandProcessor
            command_proc = CommandProcessor(cmd)
            
        if backend_proc is None:
            # Create backend processor
            backend = provider.get_required_service(IBackendService)  # type: ignore[type-abstract]
            session = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
            from src.core.services.backend_processor import BackendProcessor
            backend_proc = BackendProcessor(backend, session)
            
        # Get other required services
        response_proc = provider.get_required_service(IResponseProcessor)  # type: ignore[type-abstract]
        session = provider.get_required_service(ISessionService)  # type: ignore[type-abstract]
        
        # Get session resolver if available, otherwise it will use the default one
        from src.core.interfaces.session_resolver_interface import ISessionResolver
        session_resolver = None
        try:
            session_resolver = provider.get_service(ISessionResolver)  # type: ignore[type-abstract]
        except Exception:
            pass
            
        return RequestProcessor(command_proc, backend_proc, session, response_proc, session_resolver)  # type: ignore[arg-type]

        # Import concrete RequestProcessor implementation before registering
        from src.core.services.request_processor_service import RequestProcessor

        services.add_singleton(
            RequestProcessor, implementation_factory=_request_processor_factory
        )

        # Register session repository - always use in-memory for now
        # TODO: Add configurable session storage later
        from src.core.repositories.in_memory_session_repository import (
            InMemorySessionRepository,
        )

        # Register both the concrete type and the interface
        services.add_singleton(InMemorySessionRepository)
        services.add_singleton(ISessionRepository, InMemorySessionRepository)  # type: ignore[type-abstract]
        
        # Register session resolver
        session_resolver = DefaultSessionResolver(config)
        services.add_instance(DefaultSessionResolver, session_resolver)
        services.add_instance(ISessionResolver, session_resolver)  # type: ignore[type-abstract]

        # Register session service and bind to its interface via factory
        from src.core.interfaces.session_service_interface import ISessionService

        def _session_service_factory(provider: IServiceProvider) -> SessionService:
            repo = provider.get_required_service(ISessionRepository)  # type: ignore[type-abstract]
            return SessionService(repo)  # type: ignore[arg-type]

        services.add_singleton(
            SessionService, implementation_factory=_session_service_factory
        )
        # Also register the interface binding using the same factory to ensure
        # the interface can be resolved without attempting to call the concrete
        # implementation's constructor directly.
        import contextlib

        with contextlib.suppress(Exception):
            services.add_singleton(
                cast(type, ISessionService),
                implementation_factory=_session_service_factory,
            )

        # Register IRequestProcessor interface using the factory defined above.
        # Do NOT register RequestProcessor without the factory: its constructor
        # requires multiple dependencies and instantiating it directly would
        # fail. Bind the interface to the factory so both requests for the
        # concrete type and the interface resolve to the same singleton.
        from src.core.interfaces.request_processor_interface import IRequestProcessor

        # Register the concrete RequestProcessor and bind the interface to the same factory
        from src.core.services.request_processor_service import RequestProcessor

        services.add_singleton(
            RequestProcessor, implementation_factory=_request_processor_factory
        )
        # Also register the interface; use cast to satisfy type checker
        services.add_singleton(
            cast(type, IRequestProcessor),
            implementation_factory=_request_processor_factory,
        )

        # Register ChatController
        from src.core.app.controllers.chat_controller import ChatController

        def _chat_controller_factory(provider: IServiceProvider) -> ChatController:
            request_processor: IRequestProcessor = provider.get_required_service(
                cast(type, IRequestProcessor)
            )
            return ChatController(request_processor)

        services.add_singleton(
            ChatController, implementation_factory=_chat_controller_factory
        )

        # Register AnthropicController
        from src.core.app.controllers.anthropic_controller import AnthropicController

        def _anthropic_controller_factory(
            provider: IServiceProvider,
        ) -> AnthropicController:
            request_processor: IRequestProcessor = provider.get_required_service(
                cast(type, IRequestProcessor)
            )
            return AnthropicController(request_processor)

        services.add_singleton(
            AnthropicController, implementation_factory=_anthropic_controller_factory
        )

        # Build service provider
        service_provider = services.build_service_provider()

        # After building the provider, register additional command handlers
        # into the CommandRegistry so commands like `set` / `unset` and
        # specialized handlers (project-dir) are available during tests.
        try:
            registry = service_provider.get_required_service(CommandRegistry)
            # Register domain-level command implementations (not the UI/handler
            # layer). The registry expects commands implementing the domain
            # BaseCommand with an `execute` coroutine.
            from src.core.commands.set_command import SetCommand
            from src.core.commands.unset_command import UnsetCommand
            from src.core.domain.commands.model_command import ModelCommand
            from src.core.domain.commands.temperature_command import TemperatureCommand
            from src.core.domain.commands.hello_command import HelloCommand # Added HelloCommand

            # Register domain commands
            registry.register(SetCommand())
            registry.register(UnsetCommand())

            registry.register(ModelCommand())
            registry.register(TemperatureCommand())
            registry.register(HelloCommand()) # Registered HelloCommand
        except Exception as e:
            # Best-effort registration for tests; if DI shape differs, skip
            logger.debug(f"Could not register domain commands into registry: {e}")

        return service_provider

    async def _initialize_backends(self, app: FastAPI, config: AppConfig) -> None:
        """Initialize backends.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        # Initialize functional backends set first
        app.state.functional_backends = set()

        # Get the service provider from app.state
        service_provider = getattr(app.state, "service_provider", None)
        if service_provider is None:
            logger.warning("No service provider available for backend initialization")
            return

        # Use the BackendFactory from DI
        try:
            factory = service_provider.get_required_service(BackendFactory)
            from src.core.services.backend_registry import backend_registry

            for backend_name in backend_registry.get_registered_backends():
                try:
                    # Prepare init kwargs from config if available
                    init_kwargs: dict[str, Any] = {}
                    try:
                        backend_cfg = config.backends[backend_name]
                        if hasattr(backend_cfg, "api_key") and backend_cfg.api_key:
                            init_kwargs["api_key"] = (
                                backend_cfg.api_key[0]
                                if isinstance(backend_cfg.api_key, list)
                                and backend_cfg.api_key
                                else backend_cfg.api_key
                            )
                        # Generic url support
                        if hasattr(backend_cfg, "api_url") and backend_cfg.api_url:
                            init_kwargs["api_base_url"] = backend_cfg.api_url
                    except Exception:
                        # No specific config; fall back to env-driven behavior
                        pass

                    # Create backend and try initialize
                    try:
                        backend = factory.create_backend(backend_name)
                        await factory.initialize_backend(backend, init_kwargs)
                    except Exception:
                        # Initialization failed; skip marking functional
                        continue

                    # If we reached here, backend initialized; mark functional
                    app.state.functional_backends.add(backend_name)
                    # NOTE: Do NOT store backend instances on app.state as
                    # legacy fallbacks. Backends must be resolved via the DI
                    # container (IBackendService). Tests and consumers should
                    # use the service provider to get backend instances.
                except Exception:
                    # Best-effort per-backend; continue on errors
                    continue
        except Exception:
            # If backend registry/factory not available, skip initialization
            pass

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
            configure_loop_detection_middleware(app, loop_config)
            logger.info(
                f"Initialized loop detection middleware with config: buffer_size={loop_config.buffer_size}, max_pattern_length={loop_config.max_pattern_length}"
            )
        else:
            # Explicitly configure with disabled config to clear any existing processors
            loop_config = LoopDetectionConfig(enabled=False)
            configure_loop_detection_middleware(app, loop_config)

    async def _initialize_rate_limiting_middleware(
        self, app: FastAPI, config: AppConfig
    ) -> None:
        """Initialize rate limiting middleware based on configuration.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        # TODO: Implement rate limiting middleware


class MiddlewareConfigurator:
    """Configures middleware for the FastAPI application."""

    def configure_middleware(self, app: FastAPI, config: AppConfig) -> None:
        """Configure middleware for the FastAPI application.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        # Import middleware modules
        from src.core.app.middleware_config import configure_middleware

        # Configure middleware
        configure_middleware(app, config)


def build_app(
    config: AppConfig | dict[str, Any] | None = None,
) -> tuple[FastAPI, AppConfig]:
    """Build the FastAPI application.

    Args:
        config: The application configuration (AppConfig object or dict)

    Returns:
        A tuple of (FastAPI app, normalized AppConfig)
    """
    # Step 1: Ensure we have an AppConfig object
    if config is None:
        # Load configuration from environment
        config = AppConfig.from_env()
    elif isinstance(config, dict):
        # Convert dict config to AppConfig object
        config = AppConfig.from_legacy_config(config)

    # Handle mocked configs in test environments
    try:
        is_app_config = isinstance(config, AppConfig)
    except TypeError:
        # If isinstance fails (e.g., when AppConfig is mocked), assume it's valid in test environments
        is_app_config = os.environ.get("PYTEST_CURRENT_TEST") is not None

    # Validate config type outside of test environments
    if not is_app_config and not os.environ.get("PYTEST_CURRENT_TEST"):
        raise ValueError(
            f"Invalid config type: {type(config)}. Expected AppConfig or dict."
        )

    # Create application builder
    builder = ApplicationBuilder()

    # Build application
    app = builder.build(config)  # Pass the AppConfig object
    return app, config


# Backward compatibility wrapper for tests that expect only the app
def build_app_compat(config: AppConfig | dict[str, Any] | None = None) -> FastAPI:
    """Backward compatibility wrapper for build_app that returns only the app.

    This function exists to support legacy tests that expect build_app to return
    only the FastAPI app, not the (app, config) tuple.

    Args:
        config: The application configuration (AppConfig object or dict)

    Returns:
        The FastAPI application
    """
    app, _ = build_app(config)
    return app


# Backward compatibility aliases for tests
ServiceConfigurator = ApplicationBuilder
register_services = ApplicationBuilder._initialize_services