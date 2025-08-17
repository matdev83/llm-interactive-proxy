"""
Hybrid Controller

Provides endpoints that can use either old or new architecture based on feature flags.
"""

from __future__ import annotations

import logging

from fastapi import Depends, Request, Response

import src.models as models
from src.anthropic_models import AnthropicMessagesRequest

# No longer need integration bridge - using SOLID architecture directly
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.request_processor import IRequestProcessor

logger = logging.getLogger(__name__)


async def get_service_provider_if_available(
    request: Request,
) -> IServiceProvider | None:
    """Get the service provider if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        The service provider or None
    """
    try:
        # First check if service provider is directly available on app state (for tests)
        if hasattr(request.app.state, "service_provider"):
            provider = request.app.state.service_provider
            if provider is not None:
                return provider

        # No bridge fallback needed - service provider should always be available
        logger.warning("Service provider not found in app state")
        return None
    except Exception as e:
        logger.debug(f"Service provider not available: {e}")
        return None


async def hybrid_chat_completions(
    http_request: Request,
    request_data: models.ChatCompletionRequest,
    service_provider: IServiceProvider | None = Depends(
        get_service_provider_if_available
    ),
) -> Response:
    """Handle chat completions using hybrid architecture.

    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider (if available)

    Returns:
        The response
    """
    if service_provider is None:
        logger.error("Service provider not available - new architecture required")
        # The legacy main.py has been deprecated and doesn't have chat_completions
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="Service provider not available")

    # Check if we should use legacy flow for backward compatibility
    # This is used for tests that expect the old behavior
    if getattr(http_request.app.state, "disable_interactive_commands", False):
        logger.debug(
            "Commands disabled - using new architecture with commands disabled"
        )
        # Set a flag for the RequestProcessor to disable command processing
        http_request.state.disable_commands = True

    logger.debug("Using new SOLID architecture for request processing")

    # Use the new RequestProcessor
    request_processor = service_provider.get_required_service(IRequestProcessor)  # type: ignore
    return await request_processor.process_request(http_request, request_data)


# Legacy flow methods have been removed


async def hybrid_anthropic_messages(
    http_request: Request,
    request_data: AnthropicMessagesRequest,
    service_provider: IServiceProvider | None = Depends(
        get_service_provider_if_available
    ),
) -> Response:
    """Handle Anthropic messages using the new SOLID architecture.

    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider (if available)

    Returns:
        The response
    """
    if service_provider is None:
        logger.error(
            "Service provider not available - this should not happen in production"
        )
        raise RuntimeError("Service provider not available")

    # Convert Anthropic request to OpenAI format
    from src.anthropic_converters import anthropic_to_openai_request

    openai_request_data = anthropic_to_openai_request(request_data)

    logger.debug("Using new SOLID architecture for Anthropic request")

    # Always use the new RequestProcessor
    request_processor = service_provider.get_required_service(IRequestProcessor)  # type: ignore
    openai_response = await request_processor.process_request(
        http_request, openai_request_data
    )

    # Convert the OpenAI response back to Anthropic format
    import json

    from fastapi import Response as FastAPIResponse

    from src.anthropic_converters import openai_to_anthropic_response

    # Parse the OpenAI response JSON
    openai_response_data = json.loads(openai_response.body.decode())

    # Convert to Anthropic format
    anthropic_response_data = openai_to_anthropic_response(openai_response_data)

    # Return as FastAPI Response with Anthropic format
    return FastAPIResponse(
        content=json.dumps(anthropic_response_data),
        media_type="application/json",
        headers=openai_response.headers,
    )
