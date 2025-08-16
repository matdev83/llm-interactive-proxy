from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from src.core.commands.handler_factory import register_command_handlers
from src.core.common.logging import get_logger, setup_logging
from src.core.config_adapter import AppConfig, _load_config
from src.core.di.services import get_service_collection, set_service_provider
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
from src.core.services.redaction_middleware import RedactionMiddleware
from src.core.services.request_processor import RequestProcessor
from src.core.services.response_middleware import (
    ContentFilterMiddleware,
    LoggingMiddleware,
    LoopDetectionMiddleware,
)
from src.core.services.response_processor import ResponseProcessor
from src.core.services.session_migration_service import (
    SessionMigrationService,
    create_session_migration_service,
)
from src.core.services.session_service import SessionService
from src.core.services.tool_call_loop_middleware import ToolCallLoopDetectionMiddleware
from src.core.services.usage_tracking_service import UsageTrackingService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application.

    Args:
        app: The FastAPI application
    """
    # Get config from app state
    legacy_config = app.state.config
    config = AppConfig.from_legacy_config(legacy_config)

    async with httpx.AsyncClient(
        timeout=config.proxy_timeout,
        follow_redirects=True,
    ) as client:
        # Store client in app state for legacy code
        app.state.httpx_client = client

        # Create service provider
        services = get_service_collection()

        # Register services
        register_services(services, app)

        # Build provider and store globally
        provider = services.build_service_provider()
        set_service_provider(provider)

        # Store provider in app state
        app.state.service_provider = provider

        # Register the config
        services.add_instance(AppConfig, config)

        # Call legacy initialization if needed
        # This will be removed once migration is complete
        if hasattr(app.state, "initialize_legacy") and callable(
            app.state.initialize_legacy
        ):
            await app.state.initialize_legacy(app)

        yield

        # Cleanup
        if hasattr(app.state, "cleanup_legacy") and callable(app.state.cleanup_legacy):
            await app.state.cleanup_legacy(app)


def register_services(services: IServiceCollection, app: FastAPI) -> None:  # type: ignore[misc]
    """Register services with the service collection.

    Args:
        services: The service collection
        app: The FastAPI application
    """
    # Register singletons from app state
    services.add_instance(FastAPI, app)
    services.add_instance(httpx.AsyncClient, app.state.httpx_client)

    # Register application services
    services.add_singleton(
        BackendFactory,
        implementation_factory=lambda sp: BackendFactory(
            sp.get_required_service(httpx.AsyncClient)
        ),
    )

    # Provide a minimal IConfig backed by app.state.config for DI consumers
    from src.core.interfaces.configuration import (
        IConfig as _IConfig,  # type: ignore[assignment]
    )

    class _AppStateConfig(_IConfig):
        def get(self, key: str, default=None):
            return app.state.config.get(key, default)

        def set(self, key: str, value):
            app.state.config[key] = value

        def has(self, key: str) -> bool:
            return key in app.state.config

        def keys(self) -> list[str]:
            return list(app.state.config.keys())

        def to_dict(self) -> dict[str, object]:
            return dict(app.state.config)

        def update(self, config: dict) -> None:
            app.state.config.update(config)

    services.add_instance(_IConfig, _AppStateConfig())  # type: ignore[arg-type, type-abstract]

    # For now, register interfaces with new implementations
    # but also maintain legacy code access for migration period

    # BackendService
    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        IBackendService,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: BackendService(  # type: ignore
            sp.get_required_service(BackendFactory),  # type: ignore
            sp.get_required_service(IRateLimiter),  # type: ignore
            sp.get_required_service(IConfig),  # type: ignore
            getattr(app.state, "backend_configs", {}),
            getattr(app.state, "failover_routes", {}),
        ),
    )

    # RequestProcessor
    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        IRequestProcessor,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: RequestProcessor(  # type: ignore
            sp.get_required_service(ICommandService),  # type: ignore
            sp.get_required_service(IBackendService),  # type: ignore
            sp.get_required_service(ISessionService),  # type: ignore
            sp.get_required_service(IResponseProcessor),  # type: ignore
        ),
    )

    # SessionService
    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        ISessionService,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: SessionService(  # type: ignore
            sp.get_required_service(ISessionRepository)  # type: ignore
        ),
    )

    # SessionMigrationService
    services.add_singleton(
        SessionMigrationService,
        implementation_factory=lambda sp: create_session_migration_service(
            sp.get_required_service(ISessionService)  # type: ignore
        ),
    )

    # CommandService
    command_registry = CommandRegistry()
    services.add_instance(CommandRegistry, command_registry)

    # Register command handlers with registry
    register_command_handlers(command_registry)

    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        ICommandService,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: CommandService(  # type: ignore
            command_registry=sp.get_required_service(CommandRegistry),  # type: ignore
            session_service=sp.get_required_service(ISessionService),  # type: ignore
        ),
    )

    # RateLimiter
    services.add_singleton(
        IRateLimiter, implementation_factory=lambda _: create_rate_limiter(app.state.config)  # type: ignore
    )

    # LoopDetector
    services.add_singleton(
        ILoopDetector, implementation_factory=lambda _: create_loop_detector(app.state.config)  # type: ignore
    )

    # ResponseProcessor
    services.add_singleton(ContentFilterMiddleware)
    services.add_singleton(LoggingMiddleware)

    # Create loop detection middleware if loop detector is available
    services.add_singleton(
        LoopDetectionMiddleware,
        implementation_factory=lambda sp: LoopDetectionMiddleware(
            sp.get_service(ILoopDetector)  # type: ignore
        ),
    )

    # Create tool call loop detection middleware
    services.add_singleton(ToolCallLoopDetectionMiddleware)

    # Create redaction middleware
    services.add_singleton(
        RedactionMiddleware,
        implementation_factory=lambda sp: RedactionMiddleware(
            api_keys=config.get("api_keys", []),
            command_prefix=config.get("command_prefix", "!/"),
        ),
    )
    
    # Create response processor with all middleware components
    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        IResponseProcessor,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: ResponseProcessor(  # type: ignore
            sp.get_service(ILoopDetector),  # type: ignore
            [
                sp.get_required_service(ContentFilterMiddleware),
                sp.get_required_service(LoggingMiddleware),
                sp.get_required_service(LoopDetectionMiddleware),  # type: ignore
                sp.get_required_service(ToolCallLoopDetectionMiddleware),
            ],
        ),
    )

    # Register repositories
    services.add_singleton(
        ISessionRepository, implementation_factory=lambda _: InMemorySessionRepository()  # type: ignore
    )
    services.add_singleton(
        IUsageRepository, implementation_factory=lambda _: InMemoryUsageRepository()  # type: ignore
    )
    services.add_singleton(
        IConfigRepository, implementation_factory=lambda _: InMemoryConfigRepository()  # type: ignore
    )

    # Register usage tracking service
    services.add_singleton(  # type: ignore[arg-type, type-abstract]
        IUsageTrackingService,  # type: ignore[type-abstract]
        implementation_factory=lambda sp: UsageTrackingService(  # type: ignore
            sp.get_required_service(IUsageRepository),  # type: ignore
        ),
    )


def build_app(
    config_path: str | Path | None = None, *, config_file: str | None = None
) -> FastAPI:
    """Build a FastAPI application.

    Args:
        config_path: Optional path to configuration file

    Returns:
        A configured FastAPI application
    """
    # Load configuration using legacy config loader
    legacy_config = _load_config()
    # Optionally merge JSON config file to support tests
    if config_file:
        try:
            import json
            from pathlib import Path as PathType

            p = PathType(config_file)
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8") or "{}")
                # Support legacy key mapping: default_backend -> backend
                if "default_backend" in data and "backend" not in data:
                    data["backend"] = data["default_backend"]
                legacy_config.update(data)
        except Exception as exc:
            logger.warning("Failed to merge config file %s: %s", config_file, exc)
    config = AppConfig.from_legacy_config(legacy_config)

    # Configure logging
    setup_logging(config)
    logger.info("Building application", config_path=config_path)

    # Create FastAPI app
    app = FastAPI(
        title="LLM Interactive Proxy",
        description="A proxy server that adds interactive features to LLM APIs",
        lifespan=lifespan,
    )

    # Store config in app state for legacy compatibility
    app.state.config = legacy_config

    # Setup app state with backend configs
    app.state.backend_configs = {}
    app.state.backends = {}
    app.state.failover_routes = config.failover_routes

    # Register routes
    from src.core.app.controllers import register_routes

    register_routes(app)

    # Configure middleware
    from src.core.app.middleware_config import configure_middleware

    configure_middleware(app, app.state.config)

    # Configure error handlers
    from src.core.app.error_handlers import configure_exception_handlers

    configure_exception_handlers(app)

    logger.info("Application built successfully")
    return app
