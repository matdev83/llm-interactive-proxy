from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from src.core.common.logging import get_logger, setup_logging
from src.core.config_adapter import AppConfig, _load_config
from src.core.di.services import get_service_collection, set_service_provider
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.di import IServiceCollection
from src.core.interfaces.rate_limiter import IRateLimiter
from src.core.interfaces.repositories import (
    IConfigRepository,
    ISessionRepository,
    IUsageRepository,
)
from src.core.interfaces.request_processor import IRequestProcessor
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService
from src.core.repositories.in_memory_config_repository import InMemoryConfigRepository
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.repositories.in_memory_usage_repository import InMemoryUsageRepository
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService
from src.core.services.command_service import CommandRegistry, CommandService
from src.core.services.rate_limiter import InMemoryRateLimiter
from src.core.services.request_processor import RequestProcessor
from src.core.services.response_middleware import (
    ContentFilterMiddleware,
    LoggingMiddleware,
)
from src.core.services.response_processor import ResponseProcessor
from src.core.services.session_service import SessionService

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


def register_services(services: IServiceCollection, app: FastAPI) -> None:
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

    # For now, register interfaces with new implementations
    # but also maintain legacy code access for migration period

    # BackendService
    services.add_singleton(
        IBackendService,
        implementation_factory=lambda sp: BackendService(
            sp.get_required_service(BackendFactory),
            sp.get_required_service(IRateLimiter),
            getattr(app.state, 'backend_configs', {}),
            getattr(app.state, 'failover_routes', {}),
        ),
    )

    # RequestProcessor
    services.add_singleton(
        IRequestProcessor,
        implementation_factory=lambda sp: RequestProcessor(
            sp.get_required_service(ICommandService),
            sp.get_required_service(IBackendService),
            sp.get_required_service(ISessionService),
        ),
    )

    # SessionService
    services.add_singleton(
        ISessionService,
        implementation_factory=lambda sp: SessionService(
            sp.get_required_service(ISessionRepository)
        ),
    )

    # CommandService
    services.add_singleton(CommandRegistry)
    services.add_singleton(
        ICommandService,
        implementation_factory=lambda sp: CommandService(
            command_registry=sp.get_required_service(CommandRegistry)
        ),
    )

    # RateLimiter
    services.add_singleton(
        IRateLimiter, implementation_factory=lambda _: InMemoryRateLimiter()
    )

    # ResponseProcessor
    services.add_singleton(ContentFilterMiddleware)
    services.add_singleton(LoggingMiddleware)
    services.add_singleton(
        IResponseProcessor,
        implementation_factory=lambda sp: ResponseProcessor(
            None,
            [
                sp.get_required_service(ContentFilterMiddleware),
                sp.get_required_service(LoggingMiddleware),
            ],
        ),
    )

    # Register repositories
    services.add_singleton(
        ISessionRepository, implementation_factory=lambda _: InMemorySessionRepository()
    )
    services.add_singleton(
        IUsageRepository, implementation_factory=lambda _: InMemoryUsageRepository()
    )
    services.add_singleton(
        IConfigRepository, implementation_factory=lambda _: InMemoryConfigRepository()
    )


def build_app(config_path: str | Path | None = None) -> FastAPI:
    """Build a FastAPI application.

    Args:
        config_path: Optional path to configuration file

    Returns:
        A configured FastAPI application
    """
    # Load configuration using legacy config loader
    legacy_config = _load_config()
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
