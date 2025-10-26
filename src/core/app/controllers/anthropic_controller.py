"""
Anthropic Controller

Handles Anthropic API endpoints.
"""

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, Response

from src.anthropic_converters import (
    _map_finish_reason,
    anthropic_to_openai_request,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)
from src.anthropic_models import AnthropicMessagesRequest
from src.core.app.controllers.request_processor_resolver import (
    resolve_request_processor,
)
from src.core.common.exceptions import (
    InitializationError,
    LLMProxyError,
)
from src.core.interfaces.di_interface import IServiceProvider
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
                decoded_content = ""
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

                    # The body_iterator from the StreamingResponse is what we need to convert
                    source_iterator = adapted_response.body_iterator

                    async def _byte_wrapper(
                        iterator: AsyncIterable[str | bytes | memoryview],
                    ) -> AsyncGenerator[bytes, None]:
                        async for chunk in iterator:
                            if isinstance(chunk, memoryview):
                                yield chunk.tobytes()
                            elif isinstance(chunk, str):
                                yield chunk.encode("utf-8")
                            else:
                                yield chunk

                    openai_stream_bytes = _byte_wrapper(source_iterator)

                    # This session ID may be None, but the converter has a fallback
                    session_id = ctx.session_id or ""

                    # The new stateful async generator that will handle the conversion
                    anthropic_stream_str = openai_stream_to_anthropic_stream(
                        openai_stream_bytes,
                        anthropic_request,
                        anthropic_request.model,
                        session_id,
                    )

                    async def _anthropic_stream() -> AsyncIterator[bytes]:
                        """Yields bytes from the converted Anthropic-formatted stream."""
                        async for chunk_str in anthropic_stream_str:
                            yield chunk_str.encode("utf-8")

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

        try:
            request_processor: IRequestProcessor = resolve_request_processor(
                service_provider
            )
        except InitializationError as exc:
            raise InitializationError(
                f"Failed to create AnthropicController: {exc}"
            ) from exc

        return AnthropicController(request_processor)
    except Exception as e:
        raise InitializationError(f"Failed to create AnthropicController: {e}") from e
