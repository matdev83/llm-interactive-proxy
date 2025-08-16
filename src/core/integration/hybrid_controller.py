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
    """Handle chat completions using the new SOLID architecture.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider (if available)
        
    Returns:
        The response
    """
    if service_provider is None:
        logger.error("Service provider not available - this should not happen in production")
        raise RuntimeError("Service provider not available")
        
    logger.debug("Using new SOLID architecture for request processing")
    
    # Always use the new RequestProcessor
    request_processor = service_provider.get_required_service(IRequestProcessor)
    return await request_processor.process_request(http_request, request_data)


async def _hybrid_legacy_flow_with_new_services(
    http_request: Request,
    request_data: models.ChatCompletionRequest,
    service_provider: IServiceProvider,
    bridge: Any,
) -> Response:
    """Handle request using legacy flow but with selective new services.
    
    This allows gradual migration by using new services within the legacy flow.
    
    Args:
        http_request: The HTTP request
        request_data: The parsed request data
        service_provider: The service provider
        bridge: The integration bridge
        
    Returns:
        The response
    """
    import copy
    import json
    
    # Extract session ID
    session_id = http_request.headers.get("x-session-id", "default")
    
    # Use new session service if enabled
    if bridge.should_use_new_service("session_service"):
        from src.core.interfaces.session_service import ISessionService
        session_service = service_provider.get_required_service(ISessionService)
        _ = await session_service.get_session(session_id)
        
        # Sync session between architectures
        await bridge.sync_session(session_id)
    else:
        # Use legacy session manager
        session_manager = http_request.app.state.session_manager
        _ = session_manager.get_session(session_id)
    
    # Process commands (using legacy for now)
    messages = copy.deepcopy(request_data.messages)
    
    # Use new backend service if enabled
    if bridge.should_use_new_service("backend_service"):
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.interfaces.backend_service import IBackendService
        
        backend_service = service_provider.get_required_service(IBackendService)
        
        # Convert to domain request
        chat_messages = [
            ChatMessage(
                role=msg.role,
                content=msg.content,
                name=getattr(msg, 'name', None),
                tool_calls=getattr(msg, 'tool_calls', None),
                tool_call_id=getattr(msg, 'tool_call_id', None),
            )
            for msg in messages
        ]
        
        chat_request = ChatRequest(
            messages=chat_messages,
            model=request_data.model,
            stream=getattr(request_data, 'stream', False),
            temperature=getattr(request_data, 'temperature', None),
            max_tokens=getattr(request_data, 'max_tokens', None),
            tools=getattr(request_data, 'tools', None),
            tool_choice=getattr(request_data, 'tool_choice', None),
            user=getattr(request_data, 'user', None),
            session_id=session_id,
            extra_body={"backend_type": "openrouter"},  # Default for now
        )
        
        # Call new backend service
        result = await backend_service.call_completion(
            chat_request, 
            stream=getattr(request_data, 'stream', False)
        )
        
        # Convert result to response
        if getattr(request_data, 'stream', False):
            # Handle streaming response
            from starlette.responses import StreamingResponse
            
            async def stream_generator():
                async for chunk in result:
                    chunk_json = json.dumps(chunk.model_dump())
                    yield f"data: {chunk_json}\n\n".encode()
                yield b"data: [DONE]\n\n"
            
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            # Handle regular response
            response_data = result.model_dump()
            return Response(content=json.dumps(response_data), media_type="application/json")
    
    else:
        # Fall back to legacy backend handling
        from src.main import chat_completions as legacy_chat_completions
        return await legacy_chat_completions(http_request, request_data)


async def hybrid_anthropic_messages(
    http_request: Request,
    request_data: Any = Body(...),
    service_provider: IServiceProvider | None = Depends(get_service_provider_if_available),
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
        logger.error("Service provider not available - this should not happen in production")
        raise RuntimeError("Service provider not available")
    
    # Convert Anthropic request to OpenAI format
    from src.anthropic_converters import anthropic_to_openai_request
    from src.anthropic_models import AnthropicMessagesRequest
    
    anthropic_req = AnthropicMessagesRequest(**request_data)
    openai_request_data = anthropic_to_openai_request(anthropic_req)
    
    logger.debug("Using new SOLID architecture for Anthropic request")
    
    # Always use the new RequestProcessor
    request_processor = service_provider.get_required_service(IRequestProcessor)
    return await request_processor.process_request(http_request, openai_request_data)