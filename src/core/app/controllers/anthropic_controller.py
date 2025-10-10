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
    _map_finish_reason,
    anthropic_to_openai_request,
    openai_stream_to_anthropic_stream,
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

            messages: list[ChatMessage] = []
            for msg in openai_request_data.get("messages", []):
                content_value = msg.get("content", "")
                message_kwargs: dict[str, Any] = {
                    "role": msg.get("role", "user"),
                    "content": content_value,
                }

                name_value = msg.get("name")
                if name_value is not None:
                    message_kwargs["name"] = name_value

                tool_calls_value = msg.get("tool_calls")
                if tool_calls_value:
                    message_kwargs["tool_calls"] = tool_calls_value

                tool_call_id_value = msg.get("tool_call_id")
                if tool_call_id_value:
                    message_kwargs["tool_call_id"] = tool_call_id_value

                messages.append(ChatMessage(**message_kwargs))

            chat_request = ChatRequest(
                messages=messages,
                model=openai_request_data.get("model", ""),
                stream=openai_request_data.get("stream", False),
                temperature=openai_request_data.get("temperature"),
                max_tokens=openai_request_data.get("max_tokens"),
                top_p=openai_request_data.get("top_p"),
                frequency_penalty=openai_request_data.get("frequency_penalty"),
                presence_penalty=openai_request_data.get("presence_penalty"),
                stop=openai_request_data.get("stop"),
                tools=openai_request_data.get("tools"),
                tool_choice=openai_request_data.get("tool_choice"),
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

                # Try to parse as JSON, but handle plain strings gracefully
                try:
                    decoded_content = body_content.decode()
                    openai_response_data = json.loads(decoded_content)
                except json.JSONDecodeError:
                    # If it's not valid JSON, treat it as a plain text response
                    openai_response_data = {
                        "choices": [
                            {
                                "message": {"content": decoded_content},
                                "finish_reason": "stop",
                            }
                        ]
                    }

                # Preferred path: if we still have access to the domain ChatResponse,
                # format Anthropic directly from it to preserve content reliably.
                try:
                    from src.core.domain.chat import ChatResponse as _ChatResponse

                    if hasattr(response, "content") and isinstance(
                        response.content, _ChatResponse
                    ):
                        cr: _ChatResponse = response.content
                        first = cr.choices[0] if cr.choices else None
                        text = first.message.content if first and first.message else ""
                        usage = cr.usage or {}
                        stop_reason = (
                            _map_finish_reason(first.finish_reason)
                            if first and first.finish_reason is not None
                            else None
                        )
                        anthropic_response_data = {
                            "id": cr.id,
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "text", "text": text or ""}],
                            "model": cr.model,
                            "stop_reason": stop_reason,
                            "stop_sequence": None,
                            "usage": {
                                "input_tokens": usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0),
                            },
                        }
                    else:
                        # Fallback: convert from OpenAI-shaped dict defensively
                        if "choices" in openai_response_data and (
                            isinstance(openai_response_data.get("choices"), list)
                        ):
                            anthropic_response_data = openai_to_anthropic_response(
                                openai_response_data
                            )
                        else:
                            # Ensure openai_response_data is a dictionary before using dict()
                            if isinstance(openai_response_data, dict):
                                anthropic_response_data = openai_response_data
                            else:
                                # Convert to a safe fallback structure
                                anthropic_response_data = {
                                    "choices": [
                                        {
                                            "message": {
                                                "content": str(openai_response_data)
                                            },
                                            "finish_reason": "stop",
                                        }
                                    ]
                                }
                except Exception:
                    # On any error, create a safe fallback structure
                    anthropic_response_data = {
                        "choices": [
                            {
                                "message": {"content": str(openai_response_data)},
                                "finish_reason": "stop",
                            }
                        ]
                    }

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
                    # Ensure Anthropic streaming endpoints advertise proper SSE headers
                    sse_content_type = "text/event-stream; charset=utf-8"

                    original_iterator = adapted_response.body_iterator

                    def _convert_chunk(chunk: bytes | str | memoryview) -> bytes:
                        if isinstance(chunk, memoryview):
                            chunk = chunk.tobytes()

                        text_chunk = (
                            chunk.decode("utf-8", errors="ignore")
                            if isinstance(chunk, bytes | bytearray)
                            else str(chunk)
                        )
                        converted = openai_stream_to_anthropic_stream(text_chunk)
                        if isinstance(converted, bytes):
                            return converted
                        return str(converted).encode("utf-8")

                    async def _anthropic_stream() -> AsyncIterator[bytes]:
                        """Convert OpenAI-formatted SSE chunks to Anthropic format."""

                        iterator = original_iterator
                        async for chunk in iterator:
                            yield _convert_chunk(chunk)

                    headers = dict(adapted_response.headers)
                    headers["content-type"] = sse_content_type
                    headers.setdefault("cache-control", "no-cache")
                    headers.setdefault("connection", "keep-alive")

                    return StreamingResponse(
                        _anthropic_stream(),
                        media_type=sse_content_type,
                        status_code=getattr(adapted_response, "status_code", 200),
                        headers=headers,
                        background=adapted_response.background,
                    )
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

                status_code = getattr(adapted_response, "status_code", 200)

                # If we're using the OpenAI format (choices), convert it to Anthropic format
                if (
                    isinstance(anthropic_response_data, dict)
                    and "choices" in anthropic_response_data
                ):
                    # Convert OpenAI format to Anthropic format using shared converter
                    anthropic_formatted = openai_to_anthropic_response(
                        anthropic_response_data
                    )
                    # Sanitize headers to remove compression hints that can confuse clients
                    raw_headers = getattr(adapted_response, "headers", {})
                    safe_headers = {
                        k: v
                        for k, v in raw_headers.items()
                        if k.lower()
                        not in (
                            "content-encoding",
                            "transfer-encoding",
                            "content-length",
                        )
                    }
                    return FastAPIResponse(
                        content=json.dumps(anthropic_formatted),
                        media_type="application/json",
                        status_code=status_code,
                        headers=safe_headers,
                    )
                else:
                    # Already in Anthropic format or custom format
                    raw_headers = getattr(adapted_response, "headers", {})
                    safe_headers = {
                        k: v
                        for k, v in raw_headers.items()
                        if k.lower()
                        not in (
                            "content-encoding",
                            "transfer-encoding",
                            "content-length",
                        )
                    }
                    return FastAPIResponse(
                        content=json.dumps(anthropic_response_data),
                        media_type="application/json",
                        status_code=status_code,
                        headers=safe_headers,
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
        from typing import cast

        request_processor: IRequestProcessor | None = service_provider.get_service(
            cast(type, IRequestProcessor)
        )
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

            cmd: ICommandService | None = service_provider.get_service(
                cast(type, ICommandService)
            )
            backend: IBackendService | None = service_provider.get_service(
                cast(type, IBackendService)
            )
            session: ISessionService | None = service_provider.get_service(
                cast(type, ISessionService)
            )
            response_proc: IResponseProcessor | None = service_provider.get_service(
                cast(type, IResponseProcessor)
            )

            if cmd and backend and session and response_proc:
                from src.core.services.backend_processor import BackendProcessor
                from src.core.services.command_processor import CommandProcessor
                from src.core.services.request_processor_service import RequestProcessor

                command_processor: CommandProcessor = CommandProcessor(cmd)
                # Attempt to retrieve application state for BackendProcessor (DIP)
                from src.core.interfaces.application_state_interface import (
                    IApplicationState,
                )

                app_state = service_provider.get_service(cast(type, IApplicationState))
                if app_state is None:
                    from src.core.services.application_state_service import (
                        ApplicationStateService,
                    )

                    # Prefer resolving the concrete implementation from the provider
                    app_state = service_provider.get_service(ApplicationStateService)

                    if app_state is None:
                        # Fall back to the global provider if available. This preserves
                        # singleton semantics for application state even when scoped
                        # providers do not expose the interface binding.
                        try:
                            from src.core.di.services import get_service_provider

                            global_provider = get_service_provider()
                        except Exception:  # pragma: no cover - diagnostics only
                            global_provider = None
                        else:
                            if global_provider is not service_provider:
                                app_state = global_provider.get_service(
                                    cast(type, IApplicationState)
                                )
                                if app_state is None:
                                    app_state = global_provider.get_service(
                                        ApplicationStateService
                                    )

                    if app_state is None:
                        # As a last resort, rely on DI to construct the singleton.
                        # This avoids creating ad-hoc instances that bypass lifecycle
                        # management and ensures downstream services share state.
                        app_state = service_provider.get_required_service(
                            ApplicationStateService
                        )
                backend_processor: BackendProcessor = BackendProcessor(
                    backend, session, app_state
                )

                # Get the new decomposed services
                from src.core.services.backend_request_manager_service import (
                    BackendRequestManager,
                )
                from src.core.services.response_manager_service import ResponseManager
                from src.core.services.session_manager_service import SessionManager

                session_resolver = service_provider.get_service(
                    cast(type, ISessionResolver)
                )
                if session_resolver is None:
                    from src.core.services.session_resolver_service import (
                        DefaultSessionResolver,
                    )

                    session_resolver = service_provider.get_service(
                        DefaultSessionResolver
                    )
                    if session_resolver is None:
                        from src.core.config.app_config import AppConfig

                        config = service_provider.get_service(AppConfig)
                        session_resolver = DefaultSessionResolver(config)
                        try:
                            from src.core.di.services import get_service_collection

                            services = get_service_collection()
                            services.add_instance(
                                DefaultSessionResolver, session_resolver
                            )
                            services.add_instance(
                                cast(type, ISessionResolver), session_resolver
                            )
                        except Exception:
                            pass

                # Get agent response formatter for ResponseManager
                from src.core.interfaces.agent_response_formatter_interface import (
                    IAgentResponseFormatter,
                )

                agent_response_formatter = service_provider.get_service(
                    cast(type, IAgentResponseFormatter)
                )
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
