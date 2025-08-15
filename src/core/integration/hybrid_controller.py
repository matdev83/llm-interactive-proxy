"""
Hybrid Controller

Provides endpoints that can use either old or new architecture based on feature flags.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, Depends, Request, Response

import src.models as models
from src.core.integration.bridge import get_integration_bridge
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.request_processor import IRequestProcessor

logger = logging.getLogger(__name__)


async def get_service_provider_if_available(request: Request) -> IServiceProvider | None:
    """Get the service provider if new architecture is available.
    
    Args:
        request: The FastAPI Request object
        
    Returns:
        The service provider or None
    """
    try:
        bridge = get_integration_bridge()
        return bridge.get_service_provider()
    except Exception as e:
        logger.debug(f"Service provider not available: {e}")
        return None


async def hybrid_chat_completions(
    http_request: Request,
    request_data: models.ChatCompletionRequest,
    service_provider: IServiceProvider | None = Depends(get_service_provider_if_available),
) -> Response:
    """Handle chat completions using either old or new architecture.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider (if available)
        
    Returns:
        The response
    """
    bridge = get_integration_bridge()
    
    # Check if we should use the new request processor
    if (service_provider is not None and 
        bridge.should_use_new_service("request_processor")):
        
        logger.debug("Using new request processor")
        
        # Use new architecture
        request_processor = service_provider.get_required_service(IRequestProcessor)
        return await request_processor.process_request(http_request, request_data)
    
    else:
        logger.debug("Using legacy request processor")
        
        # Fall back to legacy architecture
        from src.main import chat_completions as legacy_chat_completions
        return await legacy_chat_completions(http_request, request_data)


async def hybrid_anthropic_messages(
    http_request: Request,
    request_data: Any = Body(...),
    service_provider: IServiceProvider | None = Depends(get_service_provider_if_available),
) -> Response:
    """Handle Anthropic messages using either old or new architecture.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider (if available)
        
    Returns:
        The response
    """
    bridge = get_integration_bridge()
    
    # Convert Anthropic request to OpenAI format
    from src.anthropic_converters import anthropic_to_openai_request
    from src.anthropic_models import AnthropicMessagesRequest
    
    anthropic_req = AnthropicMessagesRequest(**request_data)
    openai_request_data = anthropic_to_openai_request(anthropic_req)
    
    # Check if we should use the new request processor
    if (service_provider is not None and 
        bridge.should_use_new_service("request_processor")):
        
        logger.debug("Using new request processor for Anthropic")
        
        # Use new architecture
        request_processor = service_provider.get_required_service(IRequestProcessor)
        return await request_processor.process_request(http_request, openai_request_data)
    
    else:
        logger.debug("Using legacy request processor for Anthropic")
        
        # Fall back to legacy architecture
        from src.main import chat_completions as legacy_chat_completions
        return await legacy_chat_completions(http_request, openai_request_data)