"""
Context translation helper for backend request manager.

This module provides translation between typed context models and middleware dicts
to preserve backward compatibility with existing response processor middleware.
"""

from __future__ import annotations

from typing import Any

from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


def build_middleware_context(
    processing_context: ResponseProcessingContext,
    request: ChatRequest,
    response_envelope: ResponseEnvelope | StreamingResponseEnvelope | None,
    request_context: RequestContext,
    is_streaming: bool = False,
) -> dict[str, Any]:
    """Build middleware context dictionary from typed context models.

    This function translates typed context models into the dict format expected by
    IResponseProcessor and StructuredOutputMiddleware, preserving all required keys
    and legacy behavior.

    Key mapping (non-streaming):
        - original_request: from ResponseProcessingContext.original_request
        - backend_response: from response_envelope parameter
        - backend_name: from ResponseProcessingContext.backend_name or ChatRequest.extra_body.backend_type (fallback)
        - model_name: from ResponseProcessingContext.model_name or ChatRequest.model (fallback)
        - session_id: from ResponseProcessingContext.session_id
        - response_schema: from ResponseProcessingContext.structured_output.response_schema (preferred) or RequestContext.processing_context.response_schema (fallback)
        - schema_name: from ResponseProcessingContext.structured_output.schema_name (preferred) or RequestContext.processing_context.schema_name (fallback)
        - request_id: from ResponseProcessingContext.structured_output.request_id (preferred) or RequestContext.processing_context.request_id (fallback)

    Additional keys (streaming):
        - client_os: from ResponseProcessingContext.client_os or processing_context.values
        - stream_id: from RequestContext.processing_context.request_id or session_id

    All keys from RequestContext.processing_context.values are merged into the result,
    with typed fields taking precedence to keep behavior consistent.

    Args:
        processing_context: Typed processing context
        request: The backend request
        response_envelope: The response envelope (may be None for some call sites)
        request_context: Request context with processing_context
        is_streaming: Whether this is for a streaming request

    Returns:
        Dictionary with all required middleware context keys
    """
    middleware_context: dict[str, Any] = {}

    # Core required keys
    if processing_context.original_request is not None:
        middleware_context["original_request"] = processing_context.original_request

    if response_envelope is not None:
        middleware_context["backend_response"] = response_envelope

    # Backend name: prefer processing_context, fallback to extra_body.backend_type, then model
    backend_name = processing_context.backend_name
    if backend_name is None:
        extra_body = getattr(request, "extra_body", None)
        if isinstance(extra_body, dict):
            backend_name = extra_body.get("backend_type")
        if backend_name is None:
            backend_name = getattr(request, "model", None)
    if backend_name is not None:
        middleware_context["backend_name"] = backend_name

    # Model name: prefer processing_context, fallback to request.model
    model_name = processing_context.model_name
    if model_name is None:
        model_name = getattr(request, "model", None)
    if model_name is not None:
        middleware_context["model_name"] = model_name

    # Session ID (required)
    middleware_context["session_id"] = processing_context.session_id

    # Structured output keys from processing_context
    if processing_context.structured_output is not None:
        middleware_context["response_schema"] = (
            processing_context.structured_output.response_schema
        )
        middleware_context["schema_name"] = (
            processing_context.structured_output.schema_name
        )
        middleware_context["request_id"] = (
            processing_context.structured_output.request_id
        )

    # Merge processing_context.values() preserving all legacy keys
    # Typed fields take precedence over processing_context values
    if request_context.processing_context is not None:
        processing_values = request_context.processing_context.values
        if isinstance(processing_values, dict):
            # Merge legacy keys, but don't overwrite typed fields
            for key, value in processing_values.items():
                if key not in middleware_context:
                    middleware_context[key] = value

            # Extract structured output keys if not already set
            if "response_schema" not in middleware_context:
                schema = processing_values.get("response_schema")
                if schema is not None:
                    middleware_context["response_schema"] = schema

            if "schema_name" not in middleware_context:
                schema_name = processing_values.get("schema_name")
                if schema_name is not None:
                    middleware_context["schema_name"] = schema_name

            if "request_id" not in middleware_context:
                request_id = processing_values.get("request_id")
                if request_id is not None:
                    middleware_context["request_id"] = request_id

    # Store RequestContext for cancellation gate resolution
    middleware_context["request_context"] = request_context

    # Streaming-specific keys
    if is_streaming:
        # client_os: prefer processing_context, fallback to processing_context.values
        client_os = processing_context.client_os
        if client_os is None and request_context.processing_context is not None:
            processing_values = request_context.processing_context.values
            if isinstance(processing_values, dict):
                client_os = processing_values.get("client_os")
        if client_os is not None:
            middleware_context["client_os"] = client_os

        # stream_id: prefer request_id from processing_context, fallback to session_id
        stream_id = middleware_context.get("request_id")
        if stream_id is None:
            stream_id = processing_context.session_id
        if stream_id is not None:
            middleware_context["stream_id"] = stream_id

    return middleware_context
