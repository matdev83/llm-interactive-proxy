"""
Chat Controller

Handles all chat completion related API endpoints.
"""

import logging
from typing import Any

from fastapi import HTTPException, Request, Response

from src.core.adapters.api_adapters import legacy_to_domain_chat_request
from src.core.common.exceptions import LoopDetectionError
from src.core.domain.chat import ChatRequest
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor

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
        self, request: Request, request_data: ChatRequest | Any
    ) -> Response:
        """Handle chat completion requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data

        Returns:
            An HTTP response
        """
        logger.info(f"Handling chat completion request: model={request_data.model}")

        try:
            # Convert legacy request to domain model if needed
            domain_request = request_data
            if not isinstance(request_data, ChatRequest):
                domain_request = legacy_to_domain_chat_request(request_data)

            # Process the request using the request processor
            return await self._processor.process_request(request, domain_request)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except LoopDetectionError as e:
            # Re-raise LoopDetectionError directly so it can be handled by proxy_exception_handler
            raise e
        except Exception as e:
            logger.error(f"Error handling chat completion: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail={"error": str(e), "type": "ChatCompletionError"}
            )

    # Legacy compatibility method has been removed in favor of direct domain model usage


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
        request_processor = service_provider.get_service(IRequestProcessor)
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

            cmd = service_provider.get_service(ICommandService)
            backend = service_provider.get_service(IBackendService)
            session = service_provider.get_service(ISessionService)
            response_proc = service_provider.get_service(IResponseProcessor)

            if cmd and backend and session and response_proc:
                from src.core.services.request_processor_service import RequestProcessor

                # Cast the abstract interface types to concrete implementations
                # The service provider is guaranteed to return concrete implementations
                concrete_cmd = cast(ICommandService, cmd)
                concrete_backend = cast(IBackendService, backend)
                concrete_session = cast(ISessionService, session)
                concrete_response_proc = cast(IResponseProcessor, response_proc)
                request_processor = RequestProcessor(
                    concrete_cmd,
                    concrete_backend,
                    concrete_session,
                    concrete_response_proc,
                )

                # Register it for future use
                # Only try to register if the service provider is a ServiceProvider instance
                # that has the _singleton_instances attribute
                from src.core.di.container import ServiceProvider

                if isinstance(service_provider, ServiceProvider):
                    # Access the _singleton_instances attribute safely
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
