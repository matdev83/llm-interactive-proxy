"""
Streaming error mapping service.

This module contains StreamingErrorMapper and handle_streaming_error
for mapping vendor exceptions to LLMProxyError.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from starlette.exceptions import HTTPException

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    LLMProxyError,
    ParsingError,
    RateLimitExceededError,
)
from src.core.domain.streaming.contracts import StreamingErrorInfo

logger = logging.getLogger(__name__)


def _merge_provider_retry_metadata(
    details: dict[str, str], detail_payload: dict[str, Any]
) -> None:
    """Copy provider retry metadata into mapped streaming error details."""

    headers = detail_payload.get("headers")
    if isinstance(headers, dict):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after is not None:
            details["retry-after"] = str(retry_after)

    retry_after_seconds = detail_payload.get("retry_after_seconds")
    if retry_after_seconds is not None:
        details["retry_after_seconds"] = str(retry_after_seconds)


class StreamingErrorMapper:
    """Centralized error mapping for streaming operations.

    This class provides a single point for mapping backend-specific exceptions
    to LLMProxyError variants, ensuring consistent error handling across all
    streaming operations.
    """

    @staticmethod
    def map_backend_error(
        error: Exception,
        provider: str,
        stream_id: str | None = None,
    ) -> LLMProxyError:
        """Map backend exception to LLMProxyError variant.

        This method converts provider-specific exceptions into standardized
        LLMProxyError types, ensuring consistent error handling and logging.

        Args:
            error: The exception to map
            provider: Provider name for context
            stream_id: Optional stream identifier for tracking

        Returns:
            Mapped LLMProxyError variant
        """
        details = {
            "provider": provider,
        }
        if stream_id:
            details["stream_id"] = stream_id

        # Map httpx timeout exceptions
        if isinstance(error, httpx.TimeoutException):
            return APITimeoutError(
                message=f"{provider} request timed out",
                details=details,
            )

        # Map httpx HTTP status errors
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            details["status_code"] = str(status_code)
            details["response_text"] = error.response.text[:500]  # Limit size

            # Map 429 to rate limit error
            if status_code == 429:
                return RateLimitExceededError(
                    message=f"{provider} rate limit exceeded",
                    details=details,
                )

            # Map other HTTP errors to BackendError
            return BackendError(
                message=f"{provider} returned HTTP {status_code}",
                backend_name=provider,
                details=details,
                status_code=status_code,
            )

        # Map FastAPI/Starlette HTTP exceptions
        if isinstance(error, HTTPException):
            status_code = error.status_code
            details["status_code"] = str(status_code)

            detail_payload = getattr(error, "detail", None)
            message = f"{provider} returned HTTP {status_code}"
            response_text: str | None = None

            if isinstance(detail_payload, dict):
                detail_message = detail_payload.get("message")
                if isinstance(detail_message, str) and detail_message.strip():
                    response_text = detail_message
                else:
                    try:
                        response_text = json.dumps(
                            detail_payload, ensure_ascii=True, default=str
                        )
                    except (TypeError, ValueError):
                        response_text = str(detail_payload)

                detail_type = detail_payload.get("type")
                if detail_type is not None:
                    details["error_type"] = detail_type
                detail_code = detail_payload.get("code")
                if detail_code is not None:
                    details["error_code"] = detail_code
                _merge_provider_retry_metadata(details, detail_payload)
            elif detail_payload is not None:
                response_text = str(detail_payload)

            if response_text:
                normalized = response_text.strip()
                if normalized and "<html" not in normalized.lower():
                    message = normalized
                details["response_text"] = normalized[:500]

            if status_code == 429:
                rate_limit_details: dict[str, Any] = dict(details)
                retry_after = details.get("retry-after")
                if retry_after is not None:
                    rate_limit_details["headers"] = {"retry-after": str(retry_after)}
                retry_after_seconds = details.get("retry_after_seconds")
                if retry_after_seconds is not None:
                    rate_limit_details["retry_after_seconds"] = retry_after_seconds
                return RateLimitExceededError(
                    message=f"{provider} rate limit exceeded",
                    details=rate_limit_details,
                )

            return BackendError(
                message=message,
                backend_name=provider,
                details=details,
                status_code=status_code,
            )

        # Map BackendError with quota_exceeded code
        if isinstance(error, BackendError):
            # Preserve the BackendError as-is, including code and status_code
            return error

        # Map httpx connection errors
        if isinstance(error, httpx.ConnectError | httpx.ConnectTimeout):
            return APIConnectionError(
                message=f"Failed to connect to {provider}",
                details=details,
            )

        # Map JSON decode errors
        if isinstance(error, json.JSONDecodeError):
            details["error_position"] = f"line {error.lineno}, col {error.colno}"
            return ParsingError(
                message=f"Invalid JSON from {provider}",
                details=details,
            )

        # Map already-mapped LLMProxyErrors (pass through)
        if isinstance(error, LLMProxyError):
            # Enrich with streaming context if not already present
            if "provider" not in error.details:
                error.details["provider"] = provider
            if stream_id and "stream_id" not in error.details:
                error.details["stream_id"] = stream_id
            return error

        # Catch-all for unexpected errors
        logger.error(
            "Unexpected error during streaming",
            exc_info=True,
            extra={"provider": provider, "stream_id": stream_id},
        )
        return BackendError(
            message=f"Unexpected error from {provider}: {error!s}",
            backend_name=provider,
            details=details,
        )


async def handle_streaming_error(
    error: Exception,
    stream_id: str | None = None,
    provider: str = "unknown",
) -> Any:  # Returns StreamingContent
    """Convert error to terminal StreamingContent chunk.

    This function creates a terminal chunk that represents an error condition,
    allowing errors to be propagated through the streaming pipeline in a
    structured way.

    Args:
        error: The exception that occurred
        stream_id: Optional stream identifier
        provider: Provider name for context

    Returns:
        Terminal StreamingContent chunk with error metadata
    """
    from src.core.domain.streaming.streaming_content import StreamingContent

    # Map the error to a standardized type
    mapped_error = StreamingErrorMapper.map_backend_error(error, provider, stream_id)

    # Determine if error is retryable
    retryable = isinstance(
        mapped_error, APITimeoutError | APIConnectionError | RateLimitExceededError
    )

    # Create typed error contract
    # Ensure code is always present and not None
    error_code = getattr(mapped_error, "code", None)
    if error_code is None:
        error_code = "unknown"

    # Extract status_code if available
    status_code: int | None = None
    if hasattr(mapped_error, "status_code"):
        status_code = mapped_error.status_code

    # For quota_exceeded errors, use 503 instead of 429
    error_code_attr = getattr(mapped_error, "code", None)  # type: ignore[attr-defined]
    if error_code_attr == "quota_exceeded":
        if status_code is None:
            status_code = 503
        # Use status_code as string for code field (test expects integer 503 in content)
        error_code = str(status_code)

    error_info = StreamingErrorInfo(
        type=type(mapped_error).__name__,
        message=str(mapped_error),
        code=error_code,
        retryable=retryable,
        status_code=status_code,
    )

    # Build metadata with typed error contract converted to dict
    # Note: StreamingContent metadata expects dict, so we convert using model_dump
    # The typed contract ensures structure validation
    metadata: dict[str, Any] = {
        "provider": provider,
        "error": error_info.model_dump(exclude_none=True),
        "finish_reason": "error",
    }

    # Only add stream_id if it's not None
    if stream_id is not None:
        metadata["stream_id"] = stream_id

    # Build error chunk content dict for quota_exceeded errors
    # Test expects content["error"]["code"] to be 503 (int), not string
    error_content: dict[str, Any] | str = ""
    error_code_attr = getattr(mapped_error, "code", None)  # type: ignore[attr-defined]
    if error_code_attr == "quota_exceeded":
        # Build OpenAI-style error chunk with integer code
        import time

        error_content = {
            "id": f"chatcmpl-error-{int(time.time())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": provider,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "error": {
                "message": str(mapped_error),
                "type": "quota_exceeded",
                "code": status_code,  # Use integer 503 for quota errors
            },
        }

    # Create terminal chunk
    return StreamingContent(
        content=error_content,
        metadata=metadata,
        is_done=True,
        is_empty=False,
        stream_id=stream_id,
    )
