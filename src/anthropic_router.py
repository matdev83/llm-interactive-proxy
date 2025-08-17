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
from src.constants import BackendType
from src.models import ChatCompletionRequest

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
    openai_request_obj = ChatCompletionRequest(**openai_request_data)

    # --- Step 2: Temporarily switch backend type so chat_completions routes to Anthropic backend

    original_backend_type = getattr(
        http_request.app.state, "backend_type", BackendType.OPENROUTER
    )
    http_request.app.state.backend_type = BackendType.ANTHROPIC

    try:
        # Get the request processor from the service provider
        from src.core.interfaces.request_processor import IRequestProcessor

        if (
            hasattr(http_request.app.state, "service_provider")
            and http_request.app.state.service_provider
        ):
            request_processor = (
                http_request.app.state.service_provider.get_required_service(
                    IRequestProcessor
                )
            )
            # Process the request using the new architecture
            openai_response = await request_processor.process_request(
                http_request, openai_request_obj
            )
        else:
            # Fall back to legacy chat_completions_func if available
            import inspect

            chat_completions_fn = getattr(
                http_request.app.state, "chat_completions_func", None
            )
            if chat_completions_fn is None or not inspect.iscoroutinefunction(
                chat_completions_fn
            ):
                raise HTTPException(
                    status_code=501,
                    detail="Anthropic endpoint not yet fully integrated - use OpenAI endpoint with anthropic backend",
                )
            openai_response = await chat_completions_fn(
                openai_request_obj, http_request
            )

        # --- Step 3: Convert response back to Anthropic format
        if isinstance(openai_response, StreamingResponse):
            return _convert_streaming_response(openai_response)
        elif isinstance(openai_response, dict):
            return openai_to_anthropic_response(openai_response[0])
        else:
            # Unknown response type - forward as-is
            return openai_response
    finally:
        # Restore original backend type
        http_request.app.state.backend_type = original_backend_type


@router.get("/v1/models")
async def anthropic_models() -> dict[str, Any]:
    """
    Anthropic /v1/models endpoint - list available models.

    Returns a list of available Anthropic models in OpenAI-compatible format.
    """
    try:
        logger.info("Anthropic models request")
        return get_anthropic_models()
    except Exception as e:
        logger.error(f"Error in anthropic_models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
