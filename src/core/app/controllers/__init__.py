"""
Controllers package for application endpoints.

This package contains controllers that handle HTTP endpoints in the application.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request

from src.core.app.controllers.chat_controller import (
    ChatCompletionRequest,
    ChatController,
    get_chat_controller,
)
from src.core.app.controllers.usage_controller import router as usage_router
from src.core.integration.bridge import get_integration_bridge
from src.core.interfaces.di import IServiceProvider

logger = logging.getLogger(__name__)


async def get_chat_controller_if_available(request: Request) -> ChatController:
    """Get a chat controller if new architecture is available.
    
    Args:
        request: The FastAPI Request object
        
    Returns:
        A configured chat controller
    """
    try:
        bridge = get_integration_bridge()
        service_provider = bridge.get_service_provider()
        if service_provider is None:
            raise Exception("Service provider not available")
        return get_chat_controller(service_provider)
    except Exception as e:
        logger.debug(f"Chat controller not available: {e}")
        raise Exception("Chat controller not available")


async def get_service_provider_dependency() -> IServiceProvider:
    """Get the service provider from the integration bridge."""
    bridge = get_integration_bridge()
    service_provider = bridge.get_service_provider()
    if service_provider is None:
        raise HTTPException(status_code=503, detail="Service provider not available")
    return service_provider


async def get_chat_controller_dependency(service_provider: IServiceProvider = Depends(get_service_provider_dependency)) -> ChatController:
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
        controller = Depends(get_chat_controller_if_available)
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
        service_provider = Depends(get_service_provider_if_available)
    ):
        return await hybrid_chat_completions(request, request_data, service_provider)
    
    @app.post("/v1/messages")
    async def compat_anthropic_messages(
        request: Request,
        request_data: dict = Body(...),
        service_provider = Depends(get_service_provider_if_available)
    ):
        return await hybrid_anthropic_messages(request, request_data, service_provider)