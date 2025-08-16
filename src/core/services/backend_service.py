from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.constants import BackendType
from src.core.common.exceptions import (
    BackendError,
    RateLimitExceededError,
)
from src.core.domain.chat import ChatRequest, ChatResponse, StreamingChatResponse
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.configuration import IConfig
from src.core.interfaces.rate_limiter import IRateLimiter
from src.core.services.backend_config_service import BackendConfigService
from src.core.services.backend_factory import BackendFactory
from src.core.services.failover_service import FailoverService
from src.models import ChatMessage, ToolDefinition

logger = logging.getLogger(__name__)


class BackendService(IBackendService):
    """Service for interacting with LLM backends.
    
    This service manages backend selection, rate limiting, and failover.
    """
    
    def __init__(
        self, 
        factory: BackendFactory, 
        rate_limiter: IRateLimiter,
        config: IConfig,
        backend_configs: dict[str, dict[str, Any]] | None = None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the backend service.
        
        Args:
            factory: The factory for creating backends
            rate_limiter: The rate limiter for API calls
            config: Application configuration
            backend_configs: Configurations for backends
            failover_routes: Routes for backend failover
        """
        self._factory = factory
        self._rate_limiter = rate_limiter
        self._config = config
        self._backend_configs = backend_configs or {}
        self._failover_routes = failover_routes or {}
        self._backends: dict[str, LLMBackend] = {}
        self._failover_service = FailoverService(config)
        self._backend_config_service = BackendConfigService()
        
    async def call_completion(
        self, 
        request: ChatRequest,
        stream: bool = False
    ) -> ChatResponse | AsyncIterator[StreamingChatResponse]:
        """Call the LLM backend for a completion.
        
        Args:
            request: The chat completion request
            stream: Whether to stream the response
            
        Returns:
            Either a complete response or an async iterator of response chunks
            
        Raises:
            BackendError: If the backend call fails
            RateLimitExceededError: If rate limits are exceeded
            ValidationError: If the request is invalid
        """
        # Determine the backend to use
        backend_type = request.extra_body.get("backend_type")
        if not backend_type:
            # Use a default if not specified
            backend_type = BackendType.OPENAI
        
        # Get or create the backend instance
        try:
            backend = await self._get_or_create_backend(backend_type)
        except Exception as e:
            raise BackendError(
                message=f"Failed to initialize backend {backend_type}",
                backend=backend_type,
                details={"error": str(e)},
            )
        
        # Check rate limits
        rate_key = f"backend:{backend_type}"
        limit_info = await self._rate_limiter.check_limit(rate_key)
        if limit_info.is_limited:
            raise RateLimitExceededError(
                message=f"Rate limit exceeded for {backend_type}",
                reset_at=limit_info.reset_at,
                limit=limit_info.limit,
                remaining=limit_info.remaining,
            )
        
        # Prepare the call parameters
        effective_model = request.model
        
        try:
            # Convert the chat request to the backend-specific format
            processed_messages = self._prepare_messages(request.messages)
            
            # Record the usage
            await self._rate_limiter.record_usage(rate_key)
            
            # Call the backend
            # In the real implementation we'd convert back and forth between our domain types
            # and the backend-specific types, but for now we pass through to the legacy interface
            from src.models import ChatCompletionRequest
            
            # Create a legacy request for the existing backend
            legacy_request = ChatCompletionRequest(
                model=request.model,
                messages=[ChatMessage(**m.model_dump()) for m in request.messages],
                stream=stream,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=[ToolDefinition(**tool) for tool in request.tools] if request.tools else None,
                tool_choice=request.tool_choice,
                user=request.user,
                **request.extra_body
            )
            
            # Apply backend-specific configuration
            legacy_request = self._backend_config_service.apply_backend_config(
                legacy_request, backend_type
            )
            
            # Call the backend
            result = await backend.chat_completions(
                request_data=legacy_request, 
                processed_messages=processed_messages,
                effective_model=effective_model
            )
            
            # Process and return the result
            if stream:
                # Result is a StreamingResponse
                if not isinstance(result, StreamingResponse):
                    raise BackendError(
                        message=f"Expected StreamingResponse but got {type(result).__name__}",
                        backend=backend_type,
                    )
                
                async def stream_processor():
                    try:
                        async for chunk in result.body_iterator:
                            # Process each chunk
                            if chunk:
                                # In a real implementation, we'd convert to our domain types
                                yield chunk
                    except Exception as e:
                        logger.error(f"Error processing stream from {backend_type}: {e!s}")
                        # Return error message as a chunk
                        error_json = json.dumps({
                            "error": {
                                "message": f"Stream processing error: {e!s}",
                                "type": "StreamingError",
                            }
                        })
                        yield f"data: {error_json}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                
                return stream_processor()
            else:
                # Result is a tuple of (response_dict, headers_dict)
                if not isinstance(result, tuple) or len(result) != 2:
                    raise BackendError(
                        message=f"Expected (dict, dict) tuple but got {type(result).__name__}",
                        backend=backend_type,
                    )
                
                response_dict, headers = result
                
                # Convert to our domain type
                try:
                    return ChatResponse(
                        id=response_dict.get("id", ""),
                        created=response_dict.get("created", 0),
                        model=response_dict.get("model", ""),
                        choices=response_dict.get("choices", []),
                        usage=response_dict.get("usage"),
                        system_fingerprint=response_dict.get("system_fingerprint"),
                    )
                except Exception as e:
                    raise BackendError(
                        message=f"Failed to parse response: {e!s}",
                        backend=backend_type,
                        backend_response=response_dict,
                    )
                
        except (BackendError, RateLimitExceededError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            # Check if this model has complex failover routes configured
            if request.model in self._failover_routes:
                try:
                    logger.info(f"Using complex failover policy for model {request.model}")
                    
                    # Get backend configuration from the request
                    from src.core.domain.configuration.backend_config import (
                        BackendConfiguration,
                    )
                    backend_config = BackendConfiguration(
                        backend_type=backend_type,
                        model=request.model,
                        failover_routes=self._failover_routes
                    )
                    
                    # Get all failover attempts
                    attempts = self._failover_service.get_failover_attempts(
                        backend_config,
                        request.model,
                        backend_type
                    )
                    
                    if not attempts:
                        logger.warning(f"No failover attempts available for model {request.model}")
                        raise BackendError(
                            message=f"No failover attempts available for model {request.model}",
                            backend=backend_type,
                        )
                    
                    # Try each attempt in order
                    last_error = None
                    for attempt in attempts:
                        try:
                            logger.info(f"Trying failover attempt: {attempt}")
                            
                            # Create a new request with the attempt's settings
                            attempt_extra_body = request.extra_body.copy()
                            attempt_extra_body["backend_type"] = attempt.backend
                            
                            attempt_request = request.model_copy(update={
                                "extra_body": attempt_extra_body,
                                "model": attempt.model
                            })
                            
                            # Recursive call with the attempt's settings
                            return await self.call_completion(attempt_request, stream=stream)
                        except Exception as attempt_error:
                            # Log the error and try the next attempt
                            logger.warning(
                                f"Failover attempt failed for {attempt.backend}:{attempt.model}: {attempt_error!s}"
                            )
                            last_error = attempt_error
                            continue
                    
                    # If we get here, all attempts failed
                    if last_error:
                        logger.error(f"All failover attempts failed. Last error: {last_error!s}")
                        raise BackendError(
                            message=f"All failover attempts failed: {last_error!s}",
                            backend=backend_type,
                        )
                except Exception as failover_error:
                    logger.error(f"Failover processing failed: {failover_error!s}")
                    raise BackendError(
                        message=f"Failover processing failed: {failover_error!s}",
                        backend=backend_type,
                    )
            
            # Handle simple backend-level failover if configured
            elif backend_type in self._failover_routes:
                fallback_info = self._failover_routes.get(backend_type, {})
                fallback_backend = fallback_info.get("backend")
                fallback_model = fallback_info.get("model")
                
                if fallback_backend:
                    logger.warning(
                        f"Primary backend {backend_type} failed with error: {e!s}. "
                        f"Attempting fallback to {fallback_backend}"
                    )
                    
                    # Create a new request with fallback settings
                    fallback_extra_body = request.extra_body.copy()
                    fallback_extra_body["backend_type"] = fallback_backend
                    
                    fallback_updates = {"extra_body": fallback_extra_body}
                    if fallback_model:
                        fallback_updates["model"] = fallback_model
                    
                    fallback_request = request.model_copy(update=fallback_updates)
                    
                    # Recursive call with fallback backend
                    return await self.call_completion(fallback_request, stream=stream)
            
            # No fallover route or all fallback attempts failed
            logger.error(f"Backend call failed: {e!s}")
            raise BackendError(
                message=f"Backend call failed: {e!s}",
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
            # Get or create the backend instance
            backend_instance = await self._get_or_create_backend(backend)
            
            # Check if the model is available
            available_models = backend_instance.get_available_models()
            if model in available_models:
                return True, None
            
            return False, f"Model {model} not available on backend {backend}"
        except Exception as e:
            return False, f"Backend validation failed: {e!s}"
    
    async def _get_or_create_backend(self, backend_type: str) -> LLMBackend:
        """Get an existing backend or create a new one.
        
        Args:
            backend_type: The type of backend
            
        Returns:
            The backend instance
            
        Raises:
            BackendError: If the backend cannot be created or initialized
        """
        if backend_type in self._backends:
            return self._backends[backend_type]
        
        try:
            # Create a new backend instance
            backend = self._factory.create_backend(backend_type)
            
            # Get config for this backend type
            config = self._backend_configs.get(backend_type, {})
            
            # Initialize the backend
            await self._factory.initialize_backend(backend, config)
            
            # Cache the backend
            self._backends[backend_type] = backend
            
            return backend
        except Exception as e:
            raise BackendError(
                message=f"Failed to create backend {backend_type}: {e!s}",
                backend=backend_type,
            )
    
    def _prepare_messages(self, messages: list[Any]) -> list[Any]:
        """Prepare messages for the backend.
        
        In a full implementation, this would handle any necessary message
        transformations. For now, it's a simple pass-through.
        
        Args:
            messages: The messages to prepare
            
        Returns:
            The prepared messages
        """
        # For now, just return the messages as-is
        # In a real implementation, this would convert between our domain types
        # and the backend's expected format
        return [m.model_dump() for m in messages]
