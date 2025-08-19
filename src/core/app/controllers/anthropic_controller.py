"""
Anthropic Controller

Handles Anthropic API endpoints.
"""

import json
import logging
from typing import Any

from fastapi import HTTPException, Request, Response

from src.anthropic_converters import (
    anthropic_to_openai_request,
    openai_to_anthropic_response,
)
from src.anthropic_models import AnthropicMessagesRequest
from src.core.common.exceptions import LoopDetectionError
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor

logger = logging.getLogger(__name__)


class AnthropicController:
    """Controller for Anthropic-related endpoints."""

    def __init__(self, request_processor: IRequestProcessor) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
        """
        self._processor = request_processor

    async def handle_anthropic_messages(
        self, request: Request, request_data: AnthropicMessagesRequest
    ) -> Response:
        """Handle Anthropic messages requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data

        Returns:
            An HTTP response
        """
        logger.info(f"Handling Anthropic messages request: model={request_data.model}")

        try:
            # Convert Anthropic request to OpenAI format
            openai_request_data: dict[str, Any] = anthropic_to_openai_request(
                request_data
            )

            # Process the request using the request processor
            openai_response = await self._processor.process_request(
                request, openai_request_data
            )

            # Convert the OpenAI response back to Anthropic format
            body_content: bytes | memoryview = openai_response.body
            if isinstance(body_content, memoryview):
                body_content = body_content.tobytes()
            openai_response_data: dict[str, Any] = json.loads(body_content.decode())

            # Convert to Anthropic format if it has the expected OpenAI structure
            # Otherwise, pass through the response as is
            anthropic_response_data: dict[str, Any]
            if "choices" in openai_response_data:
                anthropic_response_data = openai_to_anthropic_response(
                    openai_response_data
                )
            else:
                anthropic_response_data = openai_response_data

            # Return as FastAPI Response with Anthropic format
            from fastapi import Response as FastAPIResponse

            return FastAPIResponse(
                content=json.dumps(anthropic_response_data),
                media_type="application/json",
                headers=openai_response.headers,
            )
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except LoopDetectionError as e:
            # Re-raise LoopDetectionError directly
            raise e
        except Exception as e:
            logger.error(f"Error handling Anthropic messages: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": str(e), "type": "AnthropicMessagesError"},
            )


def get_anthropic_controller(service_provider: IServiceProvider) -> AnthropicController:
    """Create an Anthropic controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured Anthropic controller
        
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
                request_processor = RequestProcessor(cmd, backend, session, response_proc)
                
                # Register it for future use
                from src.core.di.container import ServiceProvider
                if isinstance(service_provider, ServiceProvider):
                    # Access the _singleton_instances attribute safely
                    singleton_instances = getattr(service_provider, '_singleton_instances', None)
                    if singleton_instances is not None:
                        singleton_instances[IRequestProcessor] = request_processor
                        singleton_instances[RequestProcessor] = request_processor
        
        if request_processor is None:
            raise Exception("Could not find or create RequestProcessor")
            
        return AnthropicController(request_processor)
    except Exception as e:
        raise Exception(f"Failed to create AnthropicController: {e}")
