"""
Anthropic Controller

Handles Anthropic API endpoints.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, Response

from src.anthropic_converters import (
    anthropic_to_openai_request,
    openai_to_anthropic_response,
)
from src.anthropic_models import AnthropicMessagesRequest
from src.core.common.exceptions import InitializationError, LLMProxyError
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
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
        self, request: Request, request_data: AnthropicMessagesRequest | dict[str, Any]
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
                anthropic_request: AnthropicMessagesRequest = request_data
            else:
                # Convert various shapes (dict, pydantic, dataclass) to a dict
                payload: dict[str, Any]
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

            # Convert the dict to a ChatRequest object
            from src.core.domain.chat import ChatMessage, ChatRequest

            messages = []
            if "messages" in openai_request_data:
                messages = [
                    ChatMessage(
                        role=msg.get("role", "user"), content=msg.get("content", "")
                    )
                    for msg in openai_request_data.get("messages", [])
                ]

            chat_request = ChatRequest(
                messages=messages,
                model=openai_request_data.get("model", ""),
                stream=openai_request_data.get("stream", False),
                temperature=openai_request_data.get("temperature", 0.7),
                max_tokens=openai_request_data.get("max_tokens", 1000),
                top_p=openai_request_data.get("top_p", 1.0),
                frequency_penalty=openai_request_data.get("frequency_penalty", 0.0),
                presence_penalty=openai_request_data.get("presence_penalty", 0.0),
                stop=openai_request_data.get("stop"),
            )

            # Process the request using the request processor
            response = await self._processor.process_request(ctx, chat_request)

            # Check if response is a coroutine and await it if needed
            import asyncio

            if asyncio.iscoroutine(response):
                response = await response

            # Convert domain response to FastAPI response
            adapted_response: Response = domain_response_to_fastapi(response)

            # Convert the OpenAI response back to Anthropic format
            # Check if the response is a streaming response
            from fastapi.responses import StreamingResponse

            if isinstance(adapted_response, StreamingResponse):
                # For streaming responses, we'll handle them separately
                openai_response_data: dict[str, Any] = {}
                anthropic_response_data: dict[str, Any] = {}
            else:
                # For regular responses, extract the body content
                body_content: bytes | memoryview = adapted_response.body
                if isinstance(body_content, memoryview):
                    body_content = body_content.tobytes()
                openai_response_data = json.loads(body_content.decode())

                # Convert to Anthropic format if it has the expected OpenAI structure
                # Otherwise, pass through the response as is
                if "choices" in openai_response_data:
                    anthropic_response_data = openai_to_anthropic_response(
                        openai_response_data
                    )
                else:
                    anthropic_response_data = openai_response_data

            # Check if streaming was requested
            is_streaming = anthropic_request.stream
            logger.info(
                f"Streaming requested: {is_streaming}, adapted_response type: {type(adapted_response)}"
            )

            # Return as FastAPI Response with appropriate format
            from fastapi import Response as FastAPIResponse
            from fastapi.responses import StreamingResponse

            if is_streaming:
                # For streaming, we need to return the adapted response directly
                # since domain_response_to_fastapi should handle streaming properly
                if logger.isEnabledFor(logging.INFO):
                    logger.info(f"Returning streaming response: {adapted_response}")
                if isinstance(adapted_response, StreamingResponse):
                    return adapted_response
                else:
                    # If somehow we got a non-streaming response but streaming was requested,
                    # convert it to a simple streaming response
                    async def simple_stream() -> AsyncIterator[bytes]:
                        if hasattr(adapted_response, "body"):
                            yield adapted_response.body
                        else:
                            yield b'data: {"error": "Unable to stream response"}\n\n'

                    return StreamingResponse(
                        simple_stream(),  # type: ignore[arg-type]
                        media_type="text/event-stream",
                        headers=getattr(adapted_response, "headers", {}),
                    )
            else:
                # For non-streaming, return Anthropic-formatted JSON response
                if logger.isEnabledFor(logging.INFO):
                    logger.info(f"Returning JSON response: {anthropic_response_data}")

                # If we're using the OpenAI format (choices), convert it to Anthropic format
                if "choices" in anthropic_response_data:
                    # Convert OpenAI format to Anthropic format
                    first_choice = anthropic_response_data["choices"][0]
                    anthropic_formatted = {
                        "id": anthropic_response_data.get(
                            "id", "msg_" + str(hash(str(anthropic_response_data)))
                        ),
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": first_choice["message"]["content"]}
                        ],
                        "model": anthropic_response_data.get("model", ""),
                        "stop_reason": first_choice.get("finish_reason", "end_turn"),
                        "stop_sequence": None,
                        "usage": anthropic_response_data.get(
                            "usage", {"input_tokens": 0, "output_tokens": 0}
                        ),
                    }
                    return FastAPIResponse(
                        content=json.dumps(anthropic_formatted),
                        media_type="application/json",
                        headers=adapted_response.headers,
                    )
                else:
                    # Already in Anthropic format or custom format
                    return FastAPIResponse(
                        content=json.dumps(anthropic_response_data),
                        media_type="application/json",
                        headers=adapted_response.headers,
                    )
        except LLMProxyError as e:
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException as e:
            # Re-raise HTTP exceptions
            raise e
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
        request_processor: IRequestProcessor | None = service_provider.get_service(
            IRequestProcessor
        )  # type: ignore[type-abstract]
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

            cmd: ICommandService | None = service_provider.get_service(ICommandService)  # type: ignore[type-abstract]
            backend: IBackendService | None = service_provider.get_service(
                IBackendService
            )  # type: ignore[type-abstract]
            session: ISessionService | None = service_provider.get_service(
                ISessionService
            )  # type: ignore[type-abstract]
            response_proc: IResponseProcessor | None = service_provider.get_service(
                IResponseProcessor
            )  # type: ignore[type-abstract]

            if cmd and backend and session and response_proc:
                from src.core.services.backend_processor import BackendProcessor
                from src.core.services.command_processor import CommandProcessor
                from src.core.services.request_processor_service import RequestProcessor

                command_processor: CommandProcessor = CommandProcessor(cmd)
                # Attempt to retrieve application state for BackendProcessor (DIP)
                from src.core.interfaces.application_state_interface import (
                    IApplicationState,
                )

                app_state = service_provider.get_service(IApplicationState)  # type: ignore[type-abstract]
                if app_state is None:
                    from src.core.services.application_state_service import (
                        ApplicationStateService,
                    )

                    app_state = ApplicationStateService()
                backend_processor: BackendProcessor = BackendProcessor(
                    backend, session, app_state
                )

                # Get the new decomposed services
                from src.core.services.backend_request_manager_service import (
                    BackendRequestManager,
                )
                from src.core.services.response_manager_service import ResponseManager
                from src.core.services.session_manager_service import SessionManager

                session_resolver = service_provider.get_service(ISessionResolver)  # type: ignore[type-abstract]
                if session_resolver is None:
                    from src.core.services.session_resolver_service import (
                        DefaultSessionResolver,
                    )

                    session_resolver = DefaultSessionResolver(None)  # type: ignore[arg-type]

                # Get agent response formatter for ResponseManager
                from src.core.interfaces.agent_response_formatter_interface import (
                    IAgentResponseFormatter,
                )

                agent_response_formatter = service_provider.get_service(IAgentResponseFormatter)  # type: ignore[type-abstract]
                if agent_response_formatter is None:
                    from src.core.services.response_manager_service import (
                        AgentResponseFormatter,
                    )

                    agent_response_formatter = AgentResponseFormatter()

                session_manager = SessionManager(session, session_resolver)
                backend_request_manager = BackendRequestManager(
                    backend_processor, response_proc
                )
                response_manager = ResponseManager(agent_response_formatter)

                request_processor = RequestProcessor(
                    command_processor,
                    session_manager,
                    backend_request_manager,
                    response_manager,
                )

                # Register it for future use
                from src.core.di.container import ServiceProvider

                if isinstance(service_provider, ServiceProvider):
                    # Access the _singleton_instances attribute safely
                    singleton_instances: dict[type, Any] | None = getattr(
                        service_provider, "_singleton_instances", None
                    )
                    if singleton_instances is not None:
                        singleton_instances[IRequestProcessor] = request_processor
                        singleton_instances[RequestProcessor] = request_processor

        if request_processor is None:
            raise InitializationError("Could not find or create RequestProcessor")

        return AnthropicController(request_processor)
    except Exception as e:
        raise InitializationError(f"Failed to create AnthropicController: {e}") from e
