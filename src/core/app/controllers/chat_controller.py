"""
Chat Controller

Handles all chat completion related API endpoints.
"""

import asyncio
import logging

from fastapi import HTTPException, Request, Response

from src.core.common.exceptions import LLMProxyError
from src.core.domain.chat import ChatRequest
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.services.backend_processor import BackendProcessor
from src.core.services.command_processor import CommandProcessor
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

logger = logging.getLogger(__name__)


class ChatController:
    """Controller for chat-related endpoints."""

    def __init__(self, request_processor: IRequestProcessor) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
        """
        self._processor = request_processor

    async def handle_chat_completion(
        self,
        request: Request,
        request_data: ChatRequest,
    ) -> Response:
        """Handle chat completion requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data as a ChatRequest

        Returns:
            An HTTP response
        """
        try:
            # Parse the request body as JSON
            domain_request = ChatRequest(**await request.json())

            logger.info(
                f"Handling chat completion request: model={domain_request.model}, processor_type={type(self._processor).__name__}, processor_id={id(self._processor)}"
            )
            if self._processor is None:
                raise HTTPException(status_code=500, detail="Processor is None")

            # Convert FastAPI Request to RequestContext and process via core processor
            ctx = fastapi_to_domain_request_context(request, attach_original=True)

            # Process the request using the request processor
            response = await self._processor.process_request(ctx, domain_request)

            # Convert domain response to FastAPI response
            # Ensure we await the response if it's a coroutine
            if asyncio.iscoroutine(response):
                response = await response

            # Ensure OpenAI Chat Completions JSON schema for non-streaming responses
            def _ensure_openai_chat_schema(content: object) -> object:
                try:
                    # If already in expected schema, return as-is
                    if isinstance(content, dict) and "choices" in content:
                        return content

                    import json as _json
                    import time
                    import uuid

                    # Normalize simple string into OpenAI-like response
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, bytes):
                        text = content.decode("utf-8", errors="ignore")
                    else:
                        # Best-effort stringify for non-dict/list types
                        try:
                            text = _json.dumps(content)
                        except Exception:
                            text = str(content)

                    return {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": getattr(domain_request, "model", "gpt-4"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": text},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                except Exception:
                    return content

            return domain_response_to_fastapi(
                response, content_converter=_ensure_openai_chat_schema
            )

        except LLMProxyError as e:
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            logger.error(f"Error handling chat completion: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": str(e), "type": "server_error"}},
            )


def get_chat_controller(service_provider: IServiceProvider) -> ChatController:
    """Create a chat controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured chat controller

    Raises:
        Exception: If the request processor could not be found or created
    """
    try:
        # Try to get the existing request processor from the service provider
        request_processor = service_provider.get_service(IRequestProcessor)  # type: ignore[type-abstract]
        if request_processor is None:
            # Try to get the concrete implementation
            from src.core.services.request_processor_service import RequestProcessor

            request_processor = service_provider.get_service(RequestProcessor)

        if request_processor is None:
            # If still not found, try to create one on the fly
            from typing import cast

            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.interfaces.command_service_interface import ICommandService
            from src.core.interfaces.response_processor_interface import (
                IResponseProcessor,
            )
            from src.core.interfaces.session_service_interface import ISessionService

            cmd = service_provider.get_service(ICommandService)  # type: ignore[type-abstract]
            backend = service_provider.get_service(IBackendService)  # type: ignore[type-abstract]
            session = service_provider.get_service(ISessionService)  # type: ignore[type-abstract]
            response_proc = service_provider.get_service(IResponseProcessor)  # type: ignore[type-abstract]

            if cmd and backend and session and response_proc:
                from src.core.services.request_processor_service import RequestProcessor

                # Cast the abstract interface types to concrete implementations
                # The service provider is guaranteed to return concrete implementations
                concrete_cmd = cast(ICommandService, cmd)
                concrete_backend = cast(IBackendService, backend)
                concrete_session = cast(ISessionService, session)
                concrete_response_proc = cast(IResponseProcessor, response_proc)
                command_processor = CommandProcessor(concrete_cmd)
                backend_processor = BackendProcessor(concrete_backend, concrete_session)

                request_processor = RequestProcessor(
                    command_processor,
                    backend_processor,
                    concrete_session,
                    concrete_response_proc,
                )

                # Register it for future use
                # Only try to register if the service provider is a ServiceProvider instance
                # that has the _singleton_instances attribute
                from src.core.di.container import ServiceProvider

                if isinstance(service_provider, ServiceProvider):
                    # Instead of mutating internal provider state, prefer registering
                    # the instance on the ServiceCollection so a rebuild would include it.
                    try:
                        from src.core.di.services import get_service_collection

                        services = get_service_collection()
                        # Register existing instance explicitly to ensure future resolutions
                        services.add_instance(IRequestProcessor, request_processor)  # type: ignore[type-abstract]
                        services.add_instance(RequestProcessor, request_processor)  # type: ignore[type-abstract]
                    except Exception:
                        # As a last resort, fall back to internal cache mutation
                        singleton_instances = getattr(
                            service_provider, "_singleton_instances", None
                        )
                        if singleton_instances is not None:
                            singleton_instances[IRequestProcessor] = request_processor
                            singleton_instances[RequestProcessor] = request_processor

        if request_processor is None:
            raise Exception("Could not find or create RequestProcessor")

        return ChatController(request_processor)
    except Exception as e:
        raise Exception(f"Failed to create ChatController: {e}")
