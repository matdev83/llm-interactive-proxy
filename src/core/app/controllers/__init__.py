"""
Controllers package for application endpoints.

This package contains controllers that handle HTTP endpoints in the application.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request

from src.anthropic_models import AnthropicMessagesRequest
from src.core.app.controllers.chat_controller import (
    ChatCompletionRequest,
    ChatController,
    get_chat_controller,
)
from src.core.app.controllers.usage_controller import router as usage_router

# No longer need integration bridge - using SOLID architecture directly
from src.core.interfaces.di import IServiceProvider

logger = logging.getLogger(__name__)


async def _ensure_service_provider_available(app: FastAPI) -> None:
    """Ensure service provider is available in app state for tests.

    This is a fallback initialization for cases where the lifespan context
    manager hasn't been called (e.g., in tests).
    """
    try:
        import httpx

        from src.core.app.application_factory import ServiceConfigurator
        from src.core.di.services import set_service_provider

        # Set up HTTP client if not present
        if not hasattr(app.state, "httpx_client"):
            app.state.httpx_client = httpx.AsyncClient()

        # Set up basic config if not present
        if not hasattr(app.state, "config"):
            app.state.config = {
                "command_prefix": "!/",
                "proxy_timeout": 300,
                "rate_limits": {
                    "default": {"limit": 60, "time_window": 60},
                },
                "api_keys": [],
                "failover_routes": {},
            }

        # Set up basic app state attributes
        if not hasattr(app.state, "backend_configs"):
            app.state.backend_configs = {}
        if not hasattr(app.state, "backends"):
            app.state.backends = {}
        if not hasattr(app.state, "failover_routes"):
            app.state.failover_routes = {}

        # Create service provider using the factory
        from src.core.config.app_config import AppConfig

        dummy_config = AppConfig()  # Create a minimal config for tests
        configurator = ServiceConfigurator()
        provider = configurator.configure_services(
            dummy_config
        )  # This now returns a built provider
        set_service_provider(provider)
        app.state.service_provider = provider

        logger.debug("Service provider initialized for tests")

    except Exception as e:
        logger.warning(f"Failed to initialize service provider: {e}")
        raise


async def get_chat_controller_if_available(request: Request) -> ChatController:
    """Get a chat controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured chat controller
    """
    try:
        # Try to get service provider from app state first (preferred method for new architecture)
        if (
            hasattr(request.app.state, "service_provider")
            and request.app.state.service_provider
        ):
            service_provider = request.app.state.service_provider
            return get_chat_controller(service_provider)

        # If service provider not available, try to initialize it for tests
        if (
            not hasattr(request.app.state, "service_provider")
            or not request.app.state.service_provider
        ):
            await _ensure_service_provider_available(request.app)
            if (
                hasattr(request.app.state, "service_provider")
                and request.app.state.service_provider
            ):
                return get_chat_controller(request.app.state.service_provider)

        # No fallback needed - service provider should always be available
        raise Exception("Service provider not available in app state")
    except Exception as e:
        logger.debug(f"Chat controller not available: {e}")
        raise Exception("Chat controller not available")


async def get_service_provider_dependency() -> IServiceProvider:
    """Get the service provider from app state."""
    # This function needs access to the request to get the app state
    # We'll modify the dependency to accept the request
    raise HTTPException(
        status_code=503, detail="Service provider dependency needs refactoring"
    )


async def get_chat_controller_dependency(
    service_provider: IServiceProvider = Depends(get_service_provider_dependency),
) -> ChatController:
    """Get a chat controller dependency.

    Args:
        service_provider: The service provider

    Returns:
        A configured chat controller
    """
    return get_chat_controller(service_provider)


def register_routes(app: FastAPI) -> None:
    """Register application routes with the FastAPI app.

    Args:
        app: The FastAPI application instance
    """
    # Register versioned endpoints
    register_versioned_endpoints(app)

    # Register backward compatibility endpoints
    register_compatibility_endpoints(app)

    # Register models endpoints
    from src.core.app.controllers.models_controller import router as models_router

    app.include_router(models_router)

    logger.info("Routes registered successfully")


def register_versioned_endpoints(app: FastAPI) -> None:
    """Register new versioned API endpoints.

    Args:
        app: The FastAPI application instance
    """

    # New v2 endpoints
    @app.post("/v2/chat/completions")
    async def chat_completions_v2(
        request: Request,
        request_data: ChatCompletionRequest,
        controller=Depends(get_chat_controller_if_available),
    ):
        return await controller.handle_chat_completion(request, request_data)

    # Include usage router
    app.include_router(usage_router)


def register_compatibility_endpoints(app: FastAPI) -> None:
    """Register backward compatibility endpoints.

    Args:
        app: The FastAPI application instance
    """
    from fastapi import Body

    # Import hybrid controller from the integration layer
    from src.core.integration.hybrid_controller import (
        get_service_provider_if_available,
        hybrid_anthropic_messages,
        hybrid_chat_completions,
    )

    # Register hybrid endpoints that can use either old or new architecture
    @app.post("/v1/chat/completions")
    async def compat_chat_completions(
        request: Request,
        request_data: ChatCompletionRequest,
        service_provider=Depends(get_service_provider_if_available),
    ):
        return await hybrid_chat_completions(request, request_data, service_provider)

    @app.post("/v1/messages")
    async def compat_anthropic_messages(
        request: Request,
        request_data: AnthropicMessagesRequest = Body(...),
        service_provider=Depends(get_service_provider_if_available),
    ):
        return await hybrid_anthropic_messages(request, request_data, service_provider)
