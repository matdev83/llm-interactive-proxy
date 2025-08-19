"""
Controllers package for application endpoints.

This package contains controllers that handle HTTP endpoints in the application.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, cast

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from starlette.responses import Response  # Added this line

# Legacy models are only used by the compatibility endpoints via the adapter layer
from src.anthropic_models import AnthropicMessagesRequest
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
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.transport.fastapi.api_adapters import dict_to_domain_chat_request

logger = logging.getLogger(__name__)


async def get_chat_controller_if_available(request: Request) -> ChatController:
    """Get a chat controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured chat controller

    Raises:
        HTTPException: If service provider or chat controller is not available.
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        raise HTTPException(status_code=503, detail="Service provider not available")

    try:
        chat_controller = service_provider.get_service(ChatController)
        if chat_controller:
            return cast(ChatController, chat_controller)
        return cast(ChatController, get_chat_controller(service_provider))
    except Exception as e:
        logger.exception(f"Failed to get ChatController from service provider: {e}")
        raise HTTPException(status_code=500, detail="Chat controller not available")


async def get_anthropic_controller_if_available(
    request: Request,
) -> AnthropicController:
    """Get an Anthropic controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured Anthropic controller

    Raises:
        HTTPException: If service provider or Anthropic controller is not available.
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        raise HTTPException(status_code=503, detail="Service provider not available")

    try:
        anthropic_controller = service_provider.get_service(AnthropicController)
        if anthropic_controller:
            return cast(AnthropicController, anthropic_controller)
        return cast(AnthropicController, get_anthropic_controller(service_provider))
    except Exception as e:
        logger.exception(
            f"Failed to get AnthropicController from service provider: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Anthropic controller not available"
        )


async def get_service_provider_dependency(request: Request) -> IServiceProvider:
    """Get the service provider from app state.

    Args:
        request: The FastAPI request object

    Returns:
        The service provider from app state

    Raises:
        HTTPException: If service provider is not available
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        raise HTTPException(status_code=503, detail="Service provider not available")
    return cast(IServiceProvider, service_provider)


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
    # Register Anthropic compatibility router (kept as separate module)
    try:
        from src.anthropic_router import router as anthropic_router

        app.include_router(anthropic_router)
    except Exception:
        # If import fails, continue without anthropic routes (tests may mock/patch this)
        logger.debug("Anthropic router not included: import failed")

    logger.info("Routes registered successfully")

    # Internal health endpoint to report DI/controller resolution status
    @app.get("/internal/health")
    async def internal_health(request: Request) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            sp = getattr(request.app.state, "service_provider", None)
            result["service_provider_present"] = sp is not None
            if sp is not None:
                try:
                    rp = sp.get_service(IRequestProcessor)
                    result["IRequestProcessor_resolvable"] = rp is not None
                except Exception as e:
                    result["IRequestProcessor_error"] = str(e)
                try:
                    cc = sp.get_service(ChatController)
                    result["ChatController_resolvable"] = cc is not None
                except Exception as e:
                    result["ChatController_error"] = str(e)
            # Also include registered descriptor names from global service collection
            try:
                from src.core.di.services import get_service_collection

                col = get_service_collection()
                names = [
                    getattr(k, "__name__", str(k))
                    for k in getattr(col, "_descriptors", {})
                ]
                result["registered_descriptors"] = names
            except Exception as e:
                result["descriptor_error"] = str(e)
            # Debug-only: log resolvability against global provider for easier diagnosis
            try:
                import logging

                from src.core.di.services import get_service_provider

                dbg = logging.getLogger("llm.di.debug")
                with contextlib.suppress(Exception):
                    gp = get_service_provider()
                    try:
                        # Use cast to satisfy mypy when checking interface resolution
                        dbg.debug(
                            "global IRequestProcessor resolvable: %s",
                            gp.get_service(cast(type, IRequestProcessor)) is not None,
                        )
                    except Exception as e:
                        dbg.debug("global IRequestProcessor resolution error: %s", e)
                    try:
                        dbg.debug(
                            "global ChatController resolvable: %s",
                            gp.get_service(ChatController) is not None,
                        )
                    except Exception as e:
                        dbg.debug("global ChatController resolution error: %s", e)
            except Exception:
                pass
        except Exception as e:
            result["error"] = str(e)
        return result


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
