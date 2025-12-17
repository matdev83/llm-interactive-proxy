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

from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    LLMProxyError,
    ParsingError,
    RateLimitExceededError,
)

logger = logging.getLogger(__name__)


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

    # Build error metadata
    error_metadata = {
        "type": type(mapped_error).__name__,
        "message": str(mapped_error),
        "code": getattr(mapped_error, "code", "unknown"),
        "retryable": retryable,
    }

    # Add status code if available
    if hasattr(mapped_error, "status_code"):
        error_metadata["status_code"] = mapped_error.status_code

    # Build metadata
    metadata: dict[str, Any] = {
        "provider": provider,
        "error": error_metadata,
        "finish_reason": "error",
    }

    # Only add stream_id if it's not None
    if stream_id is not None:
        metadata["stream_id"] = stream_id

    # Create terminal chunk
    return StreamingContent(
        content="",
        metadata=metadata,
        is_done=True,
        is_empty=False,
        stream_id=stream_id,
    )
