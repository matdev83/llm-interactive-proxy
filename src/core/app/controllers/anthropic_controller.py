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
from src.core.common.exceptions import LLMProxyError
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

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
        self,
        request: Request,
        request_data: (
            AnthropicMessagesRequest | DomainModel | InternalDTO | dict[str, Any]
        ),
    ) -> Response:
        """Handle Anthropic messages requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data

        Returns:
            An HTTP response
        """
        try:
            # Convert Anthropic request to OpenAI format
            # Ensure we operate on AnthropicMessagesRequest for converters
            # Normalize request_data into a concrete AnthropicMessagesRequest
            import dataclasses

            if isinstance(request_data, AnthropicMessagesRequest):
                anthropic_request = request_data
            else:
                # Convert various shapes (dict, pydantic, dataclass) to a dict
                if isinstance(request_data, dict):
                    payload = request_data
                elif hasattr(request_data, "model_dump"):
                    payload = request_data.model_dump()
                elif hasattr(request_data, "dict"):
                    payload = request_data.dict()
                elif dataclasses.is_dataclass(request_data):
                    payload = dataclasses.asdict(request_data)
                else:
                    # Fallback: try to coerce to dict via vars() for objects with __dict__
                    try:
                        payload = vars(request_data)  # type: ignore[arg-type]
                    except Exception:
                        # Last resort: empty payload
                        payload = {}

                anthropic_request = AnthropicMessagesRequest(**(payload or {}))

            logger.info(
                f"Handling Anthropic messages request: model={anthropic_request.model}"
            )

            openai_request_data: dict[str, Any] = anthropic_to_openai_request(
                anthropic_request
            )

            # Convert FastAPI Request to RequestContext and process via core processor
            ctx = fastapi_to_domain_request_context(request, attach_original=True)

            # Process the request using the request processor
            response = await self._processor.process_request(ctx, openai_request_data)

            # Convert domain response to FastAPI response
            adapted_response = domain_response_to_fastapi(response)

            # Convert the OpenAI response back to Anthropic format
            body_content: bytes | memoryview = adapted_response.body
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
                headers=adapted_response.headers,
            )
        except LLMProxyError as e:
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            logger.error(f"Error handling Anthropic messages: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": str(e), "type": "server_error"}},
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
                from src.core.services.backend_processor import BackendProcessor
                from src.core.services.command_processor import CommandProcessor
                from src.core.services.request_processor_service import RequestProcessor

                command_processor = CommandProcessor(cmd)
                backend_processor = BackendProcessor(backend, session)

                request_processor = RequestProcessor(
                    command_processor, backend_processor, session, response_proc
                )

                # Register it for future use
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

        return AnthropicController(request_processor)
    except Exception as e:
        raise Exception(f"Failed to create AnthropicController: {e}")
