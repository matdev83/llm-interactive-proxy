"""
Legacy Backend Adapter

Bridges the legacy backend system with the new IBackendService interface.
This adapter allows the new architecture to use existing backend implementations
while providing a clean interface for the new code.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.common.exceptions import BackendError
from src.core.domain.chat import (
    ChatRequest,
    ChatResponse,
    StreamingChatResponse,
)
from src.core.interfaces.backend_service import IBackendService
from src.models import FunctionCall, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class LegacyBackendAdapter(IBackendService):
    """Adapter that wraps legacy backend system to implement IBackendService interface."""
    
    def __init__(self, app_state: Any):
        """Initialize the adapter with app state containing legacy backends.
        
        Args:
            app_state: The FastAPI app state containing legacy backend objects
        """
        self._app_state = app_state
        self._backend_callers = getattr(app_state, 'backend_callers', {})
        self._backends = getattr(app_state, 'backends', {})
    
    async def call_completion(
        self, 
        request: ChatRequest,
        stream: bool = False
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        """Call the LLM backend for a completion using legacy system.
        
        Args:
            request: The chat completion request
            stream: Whether to stream the response
            
        Returns:
            Either a complete response or an async iterator of response chunks
            
        Raises:
            BackendError: If the backend call fails
        """
        # Determine backend type from request
        backend_type = request.extra_body.get("backend_type", "openrouter") if request.extra_body else "openrouter"
        
        # Get the legacy backend caller
        backend_caller = self._backend_callers.get(backend_type)
        if not backend_caller:
            raise BackendError(
                message=f"Backend {backend_type} not available",
                backend=backend_type,
            )
        
        try:
            # Convert our domain request to legacy format
            legacy_request = self._convert_to_legacy_request(request)
            
            # Prepare messages for legacy system
            processed_messages = [msg.model_dump() for msg in request.messages]
            
            # Get session (simplified for now)
            session_id = request.session_id or "default"
            session = self._get_legacy_session(session_id)
            
            # Call the legacy backend
            result = await backend_caller(
                request_data=legacy_request,
                processed_messages=processed_messages,
                effective_model=request.model,
                proxy_state=session.proxy_state if session else None,
                session=session,
            )
            
            # Convert result back to our domain types
            if stream:
                # For streaming, we need to process the response iterator
                return self._process_streaming_result(result)
            else:
                # For non-streaming, convert the response
                return self._convert_from_legacy_response(result)
                
        except Exception as e:
            logger.exception(f"Legacy backend call failed: {e}")
            raise BackendError(
                message=f"Legacy backend call failed: {e!s}",
                backend=backend_type,
            )
    
    async def validate_backend_and_model(
        self,
        backend: str,
        model: str
    ) -> tuple[bool, str | None]:
        """Validate that a backend and model combination is valid.
        
        Args:
            backend: The backend identifier
            model: The model identifier
            
        Returns:
            A tuple of (is_valid, error_message)
        """
        try:
            # Get the legacy backend instance
            backend_instance = self._backends.get(backend)
            if not backend_instance:
                return False, f"Backend {backend} not available"
            
            # Check if the model is available
            available_models = backend_instance.get_available_models()
            if model in available_models:
                return True, None
            
            return False, f"Model {model} not available on backend {backend}"
        except Exception as e:
            return False, f"Backend validation failed: {e!s}"
    
    def _convert_to_legacy_request(self, request: ChatRequest) -> Any:
        """Convert our domain request to legacy format.
        
        Args:
            request: Our domain request
            
        Returns:
            Legacy request object
        """
        from src.models import ChatCompletionRequest, ChatMessage
        
        # Convert messages
        legacy_messages = []
        for msg in request.messages:
            # Convert tool_calls if present
            tool_calls_list = None
            if msg.tool_calls:
                tool_calls_list = []
                for tool_call_dict in msg.tool_calls:
                    if isinstance(tool_call_dict, dict):
                        # Convert dict to ToolCall object
                        function_call = FunctionCall(
                            name=tool_call_dict.get("function", {}).get("name", ""),
                            arguments=tool_call_dict.get("function", {}).get("arguments", "")
                        )
                        tool_call = ToolCall(
                            id=tool_call_dict.get("id", ""),
                            type=tool_call_dict.get("type", "function"),
                            function=function_call
                        )
                        tool_calls_list.append(tool_call)
                    else:
                        tool_calls_list.append(tool_call_dict)
            
            legacy_messages.append(ChatMessage(
                role=msg.role,
                content=msg.content,
                name=msg.name,
                tool_calls=tool_calls_list,
                tool_call_id=msg.tool_call_id,
            ))
        
        # Convert tools if present
        legacy_tools = None
        if request.tools:
            legacy_tools = [ToolDefinition(**tool) for tool in request.tools]
        
        # Create legacy request
        extra_params = request.extra_body or {}
        return ChatCompletionRequest(
            model=request.model,
            messages=legacy_messages,
            stream=request.stream,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=legacy_tools,
            tool_choice=request.tool_choice,
            user=request.user,
            **extra_params
        )
    
    def _convert_from_legacy_response(self, result: Any) -> ChatResponse:
        """Convert legacy response to our domain type.
        
        Args:
            result: Legacy response (tuple of response_dict, headers)
            
        Returns:
            Our domain response
        """
        if isinstance(result, tuple) and len(result) == 2:
            response_dict, headers = result
        else:
            # Handle case where result is just the response dict
            response_dict = result
        
        # Convert to our domain type using the existing method
        return ChatResponse.from_legacy_response(response_dict)
    
    async def _process_streaming_result(self, result: Any) -> AsyncIterator[StreamingChatResponse]:
        """Process streaming result from legacy backend.
        
        Args:
            result: Legacy streaming result
            
        Yields:
            Streaming chat response chunks
        """
        # This is a simplified implementation
        # In reality, we'd need to handle the specific streaming format
        # from the legacy backend
        
        if hasattr(result, 'body_iterator'):
            # It's a StreamingResponse
            async for chunk in result.body_iterator:
                if chunk:
                    try:
                        # Try to parse as JSON and convert to our domain type
                        import json
                        chunk_str = chunk.decode('utf-8') if isinstance(chunk, bytes) else str(chunk)
                        
                        # Handle SSE format
                        if chunk_str.startswith('data: '):
                            json_str = chunk_str[6:].strip()
                            if json_str == '[DONE]':
                                break
                            
                            chunk_data = json.loads(json_str)
                            yield StreamingChatResponse.from_legacy_chunk(chunk_data)
                    except Exception as e:
                        logger.warning(f"Failed to parse streaming chunk: {e}")
                        continue
        else:
            # Handle other streaming formats
            logger.warning(f"Unexpected streaming result type: {type(result)}")
    
    def _get_legacy_session(self, session_id: str) -> Any:
        """Get a legacy session object.
        
        Args:
            session_id: The session ID
            
        Returns:
            Legacy session object or None
        """
        session_manager = getattr(self._app_state, 'session_manager', None)
        if session_manager:
            return session_manager.get_session(session_id)
        return None


def create_legacy_backend_adapter(app_state: Any) -> LegacyBackendAdapter:
    """Create a legacy backend adapter.
    
    Args:
        app_state: The FastAPI app state
        
    Returns:
        A legacy backend adapter
    """
    return LegacyBackendAdapter(app_state)