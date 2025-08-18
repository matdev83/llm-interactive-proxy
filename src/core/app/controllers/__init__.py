"""
Controllers package for application endpoints.

This package contains controllers that handle HTTP endpoints in the application.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from starlette.responses import Response  # Added this line

# Legacy models are only used by the compatibility endpoints via the adapter layer
from src.anthropic_models import AnthropicMessagesRequest
from src.core.adapters.api_adapters import dict_to_domain_chat_request
from src.core.app.controllers.anthropic_controller import (
    AnthropicController,
    get_anthropic_controller,
)
from src.core.app.controllers.chat_controller import (
    ChatController,
    get_chat_controller,
)
from src.core.app.controllers.usage_controller import router as usage_router

# Import domain models for type annotations
from src.core.domain.chat import ChatRequest as DomainChatRequest

# No longer need integration bridge - using SOLID architecture directly
from src.core.interfaces.di_interface import IServiceProvider

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

        # Use AppConfig instead of app.state.config
        from src.core.config.app_config import AppConfig

        dummy_config = AppConfig()  # Create a minimal config for tests

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
        builder = (
            ServiceConfigurator()
        )  # Use builder instead of configurator for clarity
        provider = await builder._initialize_services(
            app, dummy_config
        )  # Call the async method
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
        # Ensure the app has a service provider
        service_provider = None

        # First try getting from app.state
        if (
            hasattr(request.app.state, "service_provider")
            and request.app.state.service_provider
        ):
            service_provider = request.app.state.service_provider

        # If not available, try to initialize it for tests
        if not service_provider:
            try:
                await _ensure_service_provider_available(request.app)
                if (
                    hasattr(request.app.state, "service_provider")
                    and request.app.state.service_provider
                ):
                    service_provider = request.app.state.service_provider
            except Exception as init_error:
                logger.debug(f"Failed to initialize service provider: {init_error}")

        # Final fallback - use global service provider if available
        if not service_provider:
            from src.core.di.services import get_service_provider

            service_provider = get_service_provider()

        # If we have a service provider, try to get the controller directly
        if service_provider:
            try:
                # Try to get the controller directly from DI container
                chat_controller = service_provider.get_service(ChatController)
                if chat_controller:
                    return chat_controller

                # If not registered directly, create using the factory function
                return get_chat_controller(service_provider)
            except Exception as controller_error:
                logger.debug(
                    f"Failed to get ChatController from service provider: {controller_error}"
                )

        raise Exception("Could not obtain a service provider or chat controller")
    except Exception as e:
        logger.debug(f"Chat controller not available: {e}")
        # Make the error more specific to help troubleshooting
        if "No service registered for" in str(e):
            raise Exception(f"Required service not registered in DI container: {e}")
        raise Exception("Chat controller not available")


async def get_anthropic_controller_if_available(
    request: Request,
) -> AnthropicController:
    """Get an Anthropic controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured Anthropic controller
    """
    try:
        # Ensure the app has a service provider
        service_provider = None

        # First try getting from app.state
        if (
            hasattr(request.app.state, "service_provider")
            and request.app.state.service_provider
        ):
            service_provider = request.app.state.service_provider

        # If not available, try to initialize it for tests
        if not service_provider:
            try:
                await _ensure_service_provider_available(request.app)
                if (
                    hasattr(request.app.state, "service_provider")
                    and request.app.state.service_provider
                ):
                    service_provider = request.app.state.service_provider
            except Exception as init_error:
                logger.debug(f"Failed to initialize service provider: {init_error}")

        # Final fallback - use global service provider if available
        if not service_provider:
            from src.core.di.services import get_service_provider

            service_provider = get_service_provider()

        # If we have a service provider, try to get the controller directly
        if service_provider:
            try:
                # Try to get the controller directly from DI container
                anthropic_controller = service_provider.get_service(AnthropicController)
                if anthropic_controller:
                    return anthropic_controller

                # If not registered directly, create using the factory function
                return get_anthropic_controller(service_provider)
            except Exception as controller_error:
                logger.debug(
                    f"Failed to get AnthropicController from service provider: {controller_error}"
                )

        raise Exception("Could not obtain a service provider or Anthropic controller")
    except Exception as e:
        logger.debug(f"Anthropic controller not available: {e}")
        # Make the error more specific to help troubleshooting
        if "No service registered for" in str(e):
            raise Exception(f"Required service not registered in DI container: {e}")
        raise Exception("Anthropic controller not available")


async def get_service_provider_dependency(request: Request) -> IServiceProvider:
    """Get the service provider from app state.

    Args:
        request: The FastAPI request object

    Returns:
        The service provider from app state

    Raises:
        HTTPException: If service provider is not available
    """
    if (
        not hasattr(request.app.state, "service_provider")
        or not request.app.state.service_provider
    ):
        # Try to initialize service provider for tests
        try:
            await _ensure_service_provider_available(request.app)
        except Exception as e:
            logger.error(f"Failed to initialize service provider: {e}")
            raise HTTPException(
                status_code=503, detail="Service provider not available"
            )

    # Cast to the correct type for mypy
    service_provider: IServiceProvider = request.app.state.service_provider
    return service_provider


async def get_chat_controller_dependency(
    request: Request,
) -> ChatController:
    """Get a chat controller dependency.

    Args:
        request: The FastAPI request object

    Returns:
        A configured chat controller
    """
    service_provider = await get_service_provider_dependency(request)
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
        request_data: DomainChatRequest,
        controller: ChatController = Depends(get_chat_controller_if_available),
    ) -> Response:
        return await controller.handle_chat_completion(request, request_data)

    # Include usage router
    app.include_router(usage_router)


def register_compatibility_endpoints(app: FastAPI) -> None:
    """Register backward compatibility endpoints.

    Args:
        app: The FastAPI application instance
    """

    # Register compatibility endpoints using direct controllers
    @app.post("/v1/chat/completions")
    async def compat_chat_completions(
        request: Request,
        request_data: dict[str, Any] = Body(...),
        controller: ChatController = Depends(get_chat_controller_if_available),
    ) -> Response:
        # Convert a raw dict (legacy shape from clients) to our domain model
        domain_request = dict_to_domain_chat_request(request_data)
        return await controller.handle_chat_completion(request, domain_request)

    @app.post("/v1/messages")
    async def compat_anthropic_messages(
        request: Request,
        request_data: AnthropicMessagesRequest = Body(...),
        controller: AnthropicController = Depends(
            get_anthropic_controller_if_available
        ),
    ) -> Response:
        return await controller.handle_anthropic_messages(request, request_data)
