from __future__ import annotations

import logging
from typing import Any

from fastapi import Body, Depends, FastAPI, Request, Response

import src.models as models
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.request_processor import IRequestProcessor

logger = logging.getLogger(__name__)


async def get_service_provider(request: Request) -> IServiceProvider:
    """Dependency to get the service provider.
    
    Args:
        request: The FastAPI Request object
        
    Returns:
        The service provider
    """
    return request.app.state.service_provider


async def chat_completions(
    http_request: Request,
    request_data: models.ChatCompletionRequest,
    service_provider: IServiceProvider = Depends(get_service_provider),
) -> Response:
    """Handle chat completions requests.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider
        
    Returns:
        The response
    """
    # Get the request processor from the service provider
    request_processor = service_provider.get_required_service(IRequestProcessor)
    
    # Process the request
    return await request_processor.process_request(http_request, request_data)


async def anthropic_messages(
    http_request: Request,
    request_data: Any = Body(...),
    service_provider: IServiceProvider = Depends(get_service_provider),
) -> Response:
    """Handle Anthropic messages requests.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider
        
    Returns:
        The response
    """
    from src.anthropic_converters import anthropic_to_openai_request
    from src.anthropic_models import AnthropicMessagesRequest
    
    # Convert Anthropic request to OpenAI format
    anthropic_req = AnthropicMessagesRequest(**request_data)
    request_data = anthropic_to_openai_request(anthropic_req)
    
    # Get the request processor from the service provider
    request_processor = service_provider.get_required_service(IRequestProcessor)
    
    # Process the request
    return await request_processor.process_request(http_request, request_data)


def register_chat_routes(app: FastAPI) -> None:
    """Register chat routes with the FastAPI application.
    
    Args:
        app: The FastAPI application
    """
    app.post("/v1/chat/completions")(chat_completions)
    app.post("/v1/messages")(anthropic_messages)
