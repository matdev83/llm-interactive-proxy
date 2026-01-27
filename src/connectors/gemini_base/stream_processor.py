"""
Streaming utilities for Gemini OAuth connectors.

This module provides helper functions for processing streaming responses
from the Code Assist API, including:
- Error chunk building
- SSE line parsing
- Usage data extraction
- Chunk filtering and validation
"""

import logging
import time
from typing import Any

from src.connectors.gemini_base.models import RateLimitErrorDetails, TokenUsage
from src.core.common.exceptions import BackendError
from src.core.domain.streaming.contracts import (
    OpenAIError,
    OpenAIErrorChoice,
    OpenAIErrorChunk,
)

logger = logging.getLogger(__name__)


def build_error_chunk(
    message: str,
    code: int = 500,
    model: str = "unknown",
    error_type: str = "server_error",
) -> OpenAIErrorChunk:
    """Build a standardized error chunk for streaming responses.

    Args:
        message: The error message to include.
        code: HTTP status code (default 500).
        model: The model name for the response.
        error_type: The type of error (e.g., "server_error", "quota_exceeded").

    Returns:
        An OpenAI-compatible error chunk.
    """
    return OpenAIErrorChunk(
        id=f"chatcmpl-error-{int(time.time())}",
        object="chat.completion.chunk",
        created=int(time.time()),
        model=model,
        choices=[OpenAIErrorChoice(index=0, delta={}, finish_reason="error")],
        error=OpenAIError(
            message=message,
            type=error_type,
            code=code,
        ),
    )


def build_auth_error_chunk(model: str = "unknown") -> OpenAIErrorChunk:
    """Build an authentication error chunk.

    Args:
        model: The model name for the response.

    Returns:
        A model representing an auth error chunk.
    """
    return build_error_chunk(
        message="Authentication failed. Please check your credentials.",
        code=401,
        model=model,
        error_type="auth_error",
    )


def build_timeout_error_chunk(model: str = "unknown") -> OpenAIErrorChunk:
    """Build a timeout error chunk.

    Args:
        model: The model name for the response.

    Returns:
        A model representing a timeout error chunk.
    """
    return build_error_chunk(
        message="Gateway timeout reaching Code Assist streaming endpoint.",
        code=504,
        model=model,
        error_type="timeout",
    )


def build_connection_error_chunk(model: str = "unknown") -> OpenAIErrorChunk:
    """Build a connection error chunk.

    Args:
        model: The model name for the response.

    Returns:
        A model representing a connection error chunk.
    """
    return build_error_chunk(
        message="Connection error reaching Code Assist streaming endpoint.",
        code=503,
        model=model,
        error_type="connection_error",
    )


def build_rate_limit_chunk(
    message: str,
    model: str = "unknown",
    is_quota_error: bool = False,
) -> OpenAIErrorChunk:
    """Build a rate limit error chunk.

    Args:
        message: The error message.
        model: The model name for the response.
        is_quota_error: If True, use quota_exceeded type and 503 code.

    Returns:
        A model representing a rate limit error chunk.
    """
    error_type = "quota_exceeded" if is_quota_error else "rate_limit_exceeded"
    code = 503 if is_quota_error else 429
    return build_error_chunk(
        message=message,
        code=code,
        model=model,
        error_type=error_type,
    )


def build_rate_limit_backend_error(
    error_payload: Any, model: str = "unknown"
) -> BackendError | None:
    """Build a BackendError from a streaming error payload when it signals rate limiting.

    Args:
        error_payload: Parsed SSE data (either the whole payload or the nested ``error`` dict).
        model: Model name for logging/context.

    Returns:
        BackendError when the payload indicates rate limiting; otherwise None.
    """
    if not isinstance(error_payload, dict):
        return None

    error_body = (
        error_payload.get("error") if "error" in error_payload else error_payload
    )
    if not isinstance(error_body, dict):
        return None

    error_code = error_body.get("code")
    error_status = str(error_body.get("status", "")).upper()

    if error_code != 429 and error_status != "RESOURCE_EXHAUSTED":
        return None

    message_val = error_body.get("message")

    # Treat "No capacity available" as a retryable rate limit error
    is_capacity_error = (
        isinstance(message_val, str) and "no capacity available" in message_val.lower()
    )

    error_type = (
        "quota_exceeded"
        if error_status == "RESOURCE_EXHAUSTED" and not is_capacity_error
        else "rate_limit_exceeded"
    )
    message = (
        f"Service temporarily unavailable due to rate limiting. Details: {message_val}"
        if isinstance(message_val, str) and message_val.strip()
        else "Service temporarily unavailable due to rate limiting."
    )

    details = error_payload

    return BackendError(
        message=message,
        code=error_type,
        status_code=429,
        details=details,
        backend_name=None,
        model=model,
    )


def parse_sse_line(line: str) -> str | None:
    """Parse a single SSE line and extract the data payload.

    Args:
        line: The raw SSE line (may be prefixed with "data: ").

    Returns:
        The data payload string, or None if line should be skipped.
    """
    if not line:
        return None

    # Skip comment lines
    if line.startswith(":"):
        return None

    # Extract data from "data: " prefix
    if line.startswith("data: "):
        return line[6:]  # Remove "data: " prefix

    return None


def is_quota_error_message(message: str) -> bool:
    """Check if an error message indicates a quota/rate limit error.

    Args:
        message: The error message to check.

    Returns:
        True if the message indicates quota exhaustion.
    """
    message_lower = message.lower()
    return any(
        indicator in message_lower
        for indicator in ("quota exceeded", "resource exhausted", "allowance")
    )


def coerce_chunk_to_dict(chunk: Any) -> dict[str, Any] | None:
    """Coerce a chunk to a dict, handling Pydantic models.

    Args:
        chunk: The chunk to coerce (dict, Pydantic model, or other).

    Returns:
        The chunk as a dict, or None if coercion failed.
    """
    if isinstance(chunk, dict):
        return chunk

    # Handle Pydantic models
    dump = getattr(chunk, "model_dump", lambda **_: None)(exclude_none=True)
    if isinstance(dump, dict):
        return dump

    return None


def normalize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize a streaming chunk in place.

    This handles:
    - Lowercasing finish_reason for consistency
    - Setting finish_reason='tool_calls' when tools are present without explicit finish

    Modifies the chunk in place and returns it for chaining.

    Args:
        chunk: The chunk to normalize.

    Returns:
        The modified chunk.
    """
    choices = chunk.get("choices") or []
    if not choices:
        return chunk

    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    # Normalize finish_reason to lowercase for consistency
    if isinstance(finish_reason, str):
        finish_reason = finish_reason.lower()
        choice["finish_reason"] = finish_reason

    # Set finish_reason for tool calls if not already set
    has_tools = bool(delta.get("tool_calls"))
    if has_tools and not finish_reason:
        choice["finish_reason"] = "tool_calls"

    return chunk


def should_skip_chunk(chunk: dict[str, Any]) -> bool:
    """Determine if a streaming chunk should be skipped.

    This filters out empty deltas while preserving:
    - Chunks with actual content
    - Usage-only chunks (important for token counting)
    - Stop chunks (needed for proper stream termination)
    - Tool call chunks
    - Reasoning chunks

    NOTE: This function assumes the chunk has already been normalized
    via normalize_chunk(). Call normalize_chunk() first if needed.

    Args:
        chunk: The chunk to evaluate (must be a dict).

    Returns:
        True if the chunk should be skipped, False otherwise.
    """
    if not chunk:
        return True

    choices = chunk.get("choices") or []

    # Preserve usage-only chunks even if choices is empty
    if not choices:
        # Don't skip if chunk has usage data; skip otherwise
        return not chunk.get("usage")

    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    has_content = bool(delta.get("content"))
    has_tools = bool(delta.get("tool_calls"))
    has_reasoning = bool(delta.get("reasoning_content") or delta.get("reasoning"))
    has_thought_sig = bool(delta.get("thought_signature"))

    # Keep chunks with content
    if has_content or has_tools or has_reasoning or has_thought_sig:
        return False

    # Preserve explicit terminal states even without content
    # Stop chunks are needed for usage data merging
    if finish_reason in {"error", "tool_calls", "stop", "stop_sequence"}:
        return False

    # Skip length/cancelled without content
    if finish_reason in {"length", "cancelled"}:
        return True

    # Skip empty chunks without meaningful content or finish reason
    return True


def process_chunk_for_streaming(chunk: Any) -> tuple[dict[str, Any] | None, bool]:
    """Process a chunk for streaming: coerce, normalize, and check if should skip.

    This is a convenience function that combines coerce_chunk_to_dict,
    normalize_chunk, and should_skip_chunk.

    Args:
        chunk: The raw chunk (dict, Pydantic model, or other).

    Returns:
        Tuple of (processed_chunk, should_skip). If coercion fails,
        returns (None, True).
    """
    chunk_dict = coerce_chunk_to_dict(chunk)
    if chunk_dict is None:
        return None, True

    normalize_chunk(chunk_dict)
    skip = should_skip_chunk(chunk_dict)
    return chunk_dict, skip


def normalize_finish_reason(chunk: dict[str, Any]) -> dict[str, Any]:
    """Normalize finish_reason to lowercase in a chunk.

    Modifies the chunk in place and returns it for chaining.

    Args:
        chunk: The chunk to normalize.

    Returns:
        The modified chunk.
    """
    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0] or {}
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str):
            choice["finish_reason"] = finish_reason.lower()
    return chunk


def extract_usage_from_response(
    response_json: dict[str, Any],
    prompt_tokens: int = 0,
) -> TokenUsage:
    """Extract token usage from a Gemini API response.

    Args:
        response_json: The parsed response JSON.
        prompt_tokens: Optional prompt token count if not in response.

    Returns:
        A TokenUsage model with prompt_tokens, completion_tokens, and total_tokens.
    """
    usage_data = response_json.get("usageMetadata", {})
    prompt = usage_data.get("promptTokenCount", prompt_tokens)
    completion = usage_data.get("candidatesTokenCount", 0)
    total = usage_data.get("totalTokenCount", prompt + completion)

    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def extract_429_error_details(
    error_detail: dict[str, Any] | str,
) -> RateLimitErrorDetails:
    """Extract error details from a 429 response.

    Args:
        error_detail: The parsed error response (dict or raw text).

    Returns:
        RateLimitErrorDetails model.
    """
    error_message = "Service temporarily unavailable due to rate limiting."
    error_type = "rate_limit_exceeded"
    error_code: int | None = 429

    if isinstance(error_detail, dict):
        detail_error = error_detail.get("error") or {}
        status_val = str(detail_error.get("status", "")).upper()
        if status_val == "RESOURCE_EXHAUSTED":
            error_type = "quota_exceeded"

        message_val = detail_error.get("message")
        if isinstance(message_val, str) and message_val.strip():
            if error_type == "quota_exceeded":
                error_message = (
                    "Service temporarily unavailable due to rate limiting. "
                    f"Details: {message_val}"
                )
            else:
                error_message = message_val

        error_code = detail_error.get("code", error_code)

    if error_type == "quota_exceeded":
        error_code = 503

    return RateLimitErrorDetails(
        message=error_message,
        error_type=error_type,
        error_code=error_code,
    )


__all__ = [
    "build_auth_error_chunk",
    "build_connection_error_chunk",
    "build_error_chunk",
    "build_rate_limit_backend_error",
    "build_rate_limit_chunk",
    "build_timeout_error_chunk",
    "coerce_chunk_to_dict",
    "extract_429_error_details",
    "extract_usage_from_response",
    "is_quota_error_message",
    "normalize_chunk",
    "normalize_finish_reason",
    "parse_sse_line",
    "process_chunk_for_streaming",
    "should_skip_chunk",
]
