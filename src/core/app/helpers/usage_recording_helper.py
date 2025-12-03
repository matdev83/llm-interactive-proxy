"""Helper functions for recording usage metrics in controllers.

This module provides utility functions that controllers can use to record
usage metrics at appropriate points in the request/response flow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.openrouter_usage import OpenRouterUsage
    from src.core.domain.traffic_leg import TrafficLeg
    from src.core.interfaces.usage_recording_interface import IUsageRecordingService
    from starlette.requests import Request

logger = logging.getLogger(__name__)


async def record_request_usage(
    usage_service: IUsageRecordingService,
    request: Request,
    session_id: str,
    backend_type: str,
    model: str,
    frontend_type: str,
    leg: TrafficLeg,
    prompt_tokens: int,
    app_title: str | None = None,
) -> str:
    """Record usage for an incoming request.

    This function should be called when a request is received at the frontend
    or when a request is sent to a backend.

    Args:
        usage_service: The usage recording service
        request: The FastAPI/Starlette request object
        session_id: Session identifier
        backend_type: Backend type (e.g., 'openai', 'anthropic', 'gemini')
        model: Model name
        frontend_type: Frontend type (e.g., 'openai', 'anthropic')
        leg: Traffic leg (CTP, PTB, BTP, PTC)
        prompt_tokens: Number of prompt tokens
        app_title: Application title (optional)

    Returns:
        Record ID that can be used to complete the record with response data
    """
    try:
        # Extract user context from request state (set by middleware)
        user_agent = getattr(request.state, "user_agent", None)
        proxy_user = getattr(request.state, "proxy_user", None)

        # Record the request
        record_id = await usage_service.record_request(
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            prompt_tokens=prompt_tokens,
            user_agent=user_agent,
            proxy_user=proxy_user,
            app_title=app_title,
        )

        # Store record ID in request state for later use
        if not hasattr(request.state, "usage_record_ids"):
            request.state.usage_record_ids = []
        request.state.usage_record_ids.append(record_id)

        return record_id
    except Exception as e:
        logger.warning(f"Failed to record request usage: {e}", exc_info=True)
        return ""


async def record_response_usage(
    usage_service: IUsageRecordingService,
    request: Request,
    record_id: str,
    completion_tokens: int,
    http_status_code: int,
    tool_call_count: int = 0,
    tool_names: list[str] | None = None,
    ttft_ms: float | None = None,
    backend_reported_usage: OpenRouterUsage | None = None,
) -> None:
    """Record usage for a response.

    This function should be called when a response is sent to the client
    or when a response is received from a backend.

    Args:
        usage_service: The usage recording service
        request: The FastAPI/Starlette request object
        record_id: The record ID returned from record_request_usage
        completion_tokens: Number of completion tokens
        http_status_code: HTTP status code
        tool_call_count: Number of tool calls (default: 0)
        tool_names: List of tool names called (optional)
        ttft_ms: Time to first token in milliseconds (optional)
        backend_reported_usage: Backend-reported usage metadata (optional)
    """
    try:
        # Extract timing from request state (set by middleware)
        request_start_time = getattr(request.state, "request_start_time", None)
        response_end_time = getattr(request.state, "response_end_time", None)
        total_duration_ms = getattr(request.state, "total_duration_ms", 0.0)

        # Calculate proxy processing time (if we have timing data)
        proxy_processing_ms = 0.0
        if request_start_time and response_end_time:
            # For now, use total duration as proxy processing time
            # In a more sophisticated implementation, we would subtract backend latency
            proxy_processing_ms = total_duration_ms

        # Extract backend-reported usage if available
        backend_reported_prompt_tokens = None
        backend_reported_completion_tokens = None
        backend_reported_cost = None

        if backend_reported_usage:
            backend_reported_prompt_tokens = backend_reported_usage.prompt_tokens
            backend_reported_completion_tokens = (
                backend_reported_usage.completion_tokens
            )
            backend_reported_cost = backend_reported_usage.cost

        # Record the response
        await usage_service.record_response(
            record_id=record_id,
            completion_tokens=completion_tokens,
            http_status_code=http_status_code,
            tool_call_count=tool_call_count,
            tool_names=tool_names,
            ttft_ms=ttft_ms,
            proxy_processing_ms=proxy_processing_ms,
            total_duration_ms=total_duration_ms,
            backend_reported_prompt_tokens=backend_reported_prompt_tokens,
            backend_reported_completion_tokens=backend_reported_completion_tokens,
            backend_reported_cost=backend_reported_cost,
        )
    except Exception as e:
        logger.warning(f"Failed to record response usage: {e}", exc_info=True)


def extract_tool_calls_from_response(response: Any) -> tuple[int, list[str]]:
    """Extract tool call information from a response.

    Args:
        response: The response object (domain model or dict)

    Returns:
        Tuple of (tool_call_count, tool_names)
    """
    tool_call_count = 0
    tool_names: list[str] = []

    try:
        # Handle domain ChatResponse
        if hasattr(response, "choices"):
            choices = response.choices
            if choices:
                for choice in choices:
                    message = getattr(choice, "message", None)
                    if message and hasattr(message, "tool_calls"):
                        tool_calls = message.tool_calls
                        if tool_calls:
                            tool_call_count += len(tool_calls)
                            for tool_call in tool_calls:
                                if hasattr(tool_call, "function"):
                                    function = tool_call.function
                                    if hasattr(function, "name"):
                                        tool_names.append(function.name)

        # Handle dict response
        elif isinstance(response, dict):
            choices = response.get("choices", [])
            for choice in choices:
                if isinstance(choice, dict):
                    message = choice.get("message", {})
                    if isinstance(message, dict):
                        tool_calls = message.get("tool_calls", [])
                        if tool_calls:
                            tool_call_count += len(tool_calls)
                            for tool_call in tool_calls:
                                if isinstance(tool_call, dict):
                                    function = tool_call.get("function", {})
                                    if isinstance(function, dict):
                                        name = function.get("name")
                                        if name:
                                            tool_names.append(name)
    except Exception as e:
        logger.warning(f"Failed to extract tool calls from response: {e}")

    return tool_call_count, tool_names


def extract_backend_reported_usage(response: Any) -> OpenRouterUsage | None:
    """Extract backend-reported usage from a response.

    Args:
        response: The response object (domain model or dict)

    Returns:
        OpenRouterUsage object if usage data is present, None otherwise
    """
    try:
        from src.core.domain.openrouter_usage import OpenRouterUsage

        # Handle domain response with usage attribute
        if hasattr(response, "usage"):
            usage = response.usage
            if usage:
                # If it's already an OpenRouterUsage object, return it
                if isinstance(usage, OpenRouterUsage):
                    return usage

                # If it's a dict, convert it
                if isinstance(usage, dict):
                    return OpenRouterUsage.from_dict(usage)

                # If it has model_dump method, use it
                if hasattr(usage, "model_dump"):
                    return OpenRouterUsage.from_dict(usage.model_dump())

        # Handle dict response
        elif isinstance(response, dict):
            usage = response.get("usage")
            if usage and isinstance(usage, dict):
                return OpenRouterUsage.from_dict(usage)

    except Exception as e:
        logger.warning(f"Failed to extract backend-reported usage: {e}")

    return None
