"""
FastAPI router for Anthropic API endpoints.
Provides /anthropic/v1/messages and /anthropic/v1/models endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response, StreamingResponse

# Conversion helpers
from src.anthropic_converters import (
    AnthropicMessagesRequest,
    anthropic_to_openai_request,
    get_anthropic_models,
    openai_stream_to_anthropic_stream,
    openai_to_anthropic_response,
)
from src.core.common.exceptions import LLMProxyError
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.transport.fastapi.api_adapters import dict_to_domain_chat_request
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

# Import will be done locally to avoid circular imports

logger = logging.getLogger(__name__)

# Create router with /anthropic prefix
router = APIRouter(prefix="/anthropic", tags=["anthropic"])


@router.post("/v1/messages")
async def anthropic_messages(
    request_body: AnthropicMessagesRequest, http_request: Request
) -> Any:
    """
    Anthropic /v1/messages endpoint - chat completions.

    Converts Anthropic request format to OpenAI format, processes through
    the existing proxy logic, then converts response back to Anthropic format.
    """

    logger.info(f"Anthropic messages request for model: {request_body.model}")

    # --- Step 1: Convert to OpenAI format
    # Basic role validation - Anthropic accepts only user/assistant/system roles
    allowed_roles = {"user", "assistant", "system"}
    for m in request_body.messages:
        if m.role not in allowed_roles:
            raise HTTPException(status_code=422, detail=f"Invalid role '{m.role}'")

    openai_request_data = anthropic_to_openai_request(request_body)
    # Convert OpenAI-format dict to domain ChatRequest
    openai_request_obj = dict_to_domain_chat_request(openai_request_data)

    # --- Step 2: Temporarily switch backend type so chat_completions routes to Anthropic backend

    ctx = fastapi_to_domain_request_context(http_request, attach_original=True)
    original_backend_type = ctx.state.get("backend_type", "openrouter")
    ctx.state["backend_type"] = "anthropic"

    try:
        # Get the request processor from the service provider
        if (
            hasattr(http_request.app.state, "service_provider")
            and http_request.app.state.service_provider
        ):
            request_processor = (
                http_request.app.state.service_provider.get_required_service(
                    IRequestProcessor
                )
            )
            # Convert to RequestContext and process using core processor
            ctx = fastapi_to_domain_request_context(http_request, attach_original=True)

            # Process the request using the domain request processor
            try:
                openai_response = await request_processor.process_request(
                    ctx, openai_request_obj
                )
            except LLMProxyError as e:
                # Map domain exceptions to HTTP exceptions
                raise map_domain_exception_to_http_exception(e)
        else:
            # No fallback to legacy chat_completions_func - require service provider
            raise HTTPException(
                status_code=501,
                detail="Anthropic endpoint requires service provider to be configured",
            )

        # --- Step 3: Convert response back to Anthropic format
        # If the processor returned a raw async generator (some tests patch
        # connectors to return async generators directly), wrap it into a
        # StreamingResponseEnvelope so the response adapter can handle it.
        try:
            import inspect
            from src.core.domain.responses import StreamingResponseEnvelope

            if inspect.isasyncgen(openai_response) or hasattr(openai_response, "__aiter__"):
                openai_response = StreamingResponseEnvelope(
                    content=openai_response,
                    media_type="text/event-stream",
                    headers={"content-type": "text/event-stream"},
                )
        except Exception:
            # Ignore wrapping errors and continue; downstream will handle faults
            pass

        # First convert domain response to FastAPI response
        fastapi_response = domain_response_to_fastapi(openai_response)

        # Then convert to Anthropic format
        if isinstance(fastapi_response, StreamingResponse):
            return _convert_streaming_response(fastapi_response)
        else:
            # Extract response body
            body_content: bytes | memoryview = fastapi_response.body
            if isinstance(body_content, memoryview):
                body_content = body_content.tobytes()

            # Parse response body
            import json

            openai_response_data = json.loads(body_content.decode())

            # Convert to Anthropic format if the response looks like OpenAI format
            # (contains 'choices'), otherwise pass it through as it's already
            # in Anthropic-compatible shape.
            if isinstance(openai_response_data, dict) and "choices" in openai_response_data:
                anthropic_response_data = openai_to_anthropic_response(openai_response_data)
            else:
                anthropic_response_data = openai_response_data

            # Return as FastAPI Response
            from fastapi import Response as FastAPIResponse

            return FastAPIResponse(
                content=json.dumps(anthropic_response_data),
                media_type="application/json",
                headers=fastapi_response.headers,
            )
    finally:
        # Restore original backend type
        ctx.state["backend_type"] = original_backend_type


@router.get("/v1/models")
async def anthropic_models() -> dict[str, Any]:
    """
    Anthropic /v1/models endpoint - list available models.

    Returns a list of available Anthropic models in OpenAI-compatible format.
    """
    try:
        logger.info("Anthropic models request")
        return get_anthropic_models()
    except LLMProxyError as e:
        # Map domain exceptions to HTTP exceptions
        raise map_domain_exception_to_http_exception(e)
    except Exception as e:
        logger.error(f"Error in anthropic_models: {e}")
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": str(e), "type": "server_error"}},
        )


def _convert_streaming_response(openai_stream_response: StreamingResponse) -> Response:
    """
    Convert OpenAI streaming response to Anthropic streaming format.

    Args:
        openai_stream_response: OpenAI StreamingResponse

    Returns:
        Anthropic-compatible StreamingResponse
    """

    if isinstance(openai_stream_response, StreamingResponse):
        # Create a new streaming response that converts chunks
        async def anthropic_stream_generator() -> AsyncGenerator[bytes, None]:
            async for chunk in openai_stream_response.body_iterator:
                if isinstance(chunk, bytes):
                    chunk_str = chunk.decode("utf-8")
                else:
                    chunk_str = str(chunk)

                # Convert each OpenAI chunk to Anthropic format
                anthropic_chunk = openai_stream_to_anthropic_stream(chunk_str)
                yield anthropic_chunk.encode("utf-8")

        return StreamingResponse(
            anthropic_stream_generator(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
            },
        )
    else:
        # If it's not a streaming response, return as-is
        return openai_stream_response  # type: ignore[return-value]


# Health check endpoint for Anthropic router
@router.get("/health")
async def anthropic_health() -> dict[str, str]:
    """Health check for Anthropic router."""
    return {"status": "healthy", "service": "anthropic-proxy"}


# Info endpoint
@router.get("/v1/info")
async def anthropic_info() -> dict[str, Any]:
    """Information about the Anthropic proxy service."""
    return {
        "service": "anthropic-proxy",
        "version": "1.0.0",
        "supported_endpoints": ["/v1/messages", "/v1/models"],
        "supported_models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ],
    }
