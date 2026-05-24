"""Exception normalizer implementation.

Translates provider exceptions to domain-specific errors.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.common.exceptions import (
    BackendError,
    InvalidRequestError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer

logger = logging.getLogger(__name__)


class ExceptionNormalizer(IExceptionNormalizer):
    """Service for normalizing provider exceptions to domain errors."""

    def normalize(self, exc: Exception, backend_type: str) -> Exception:
        """Translate provider exception to a domain error when possible.

        Translation rules (based on duck-typed exception attributes):
        - status_code == 429 -> RateLimitExceededError
        - 400 <= status_code < 500 -> InvalidRequestError
        - other int status_code -> BackendError

        Never raises; always returns a normalized exception (or the original).
        """
        if isinstance(exc, LLMProxyError | BackendError | RateLimitExceededError):
            return exc

        status_code = getattr(exc, "status_code", None)
        if not isinstance(status_code, int):
            return exc

        detail_payload = getattr(exc, "detail", None)
        headers = getattr(exc, "headers", None)

        if status_code == 429:
            message: str | None = None

            if isinstance(detail_payload, dict):
                message = detail_payload.get("message")
                if not message:
                    error_block = detail_payload.get("error")
                    if isinstance(error_block, dict):
                        message = error_block.get("message")
            if not message and detail_payload is not None:
                message = str(detail_payload)
            if not message:
                message = "Rate limit exceeded"

            retry_after_seconds: float | None = None
            if isinstance(headers, dict):
                retry_after_raw = headers.get("Retry-After") or headers.get(
                    "retry-after"
                )
                if retry_after_raw is not None:
                    try:
                        retry_after_seconds = float(retry_after_raw)
                    except (TypeError, ValueError):
                        retry_after_seconds = None

            reset_at = (
                time.time() + retry_after_seconds
                if isinstance(retry_after_seconds, int | float)
                else None
            )

            serialized_detail: Any
            if isinstance(
                detail_payload,
                dict | list | tuple | str | int | float | bool | type(None),
            ):
                serialized_detail = detail_payload
            else:
                serialized_detail = str(detail_payload)

            details: dict[str, Any] = {
                "backend": backend_type,
                "status_code": 429,
                "detail": serialized_detail,
            }

            if isinstance(headers, dict) and headers:
                allowed_header_names = {"retry-after"}
                allowlisted_headers: dict[str, Any] = {
                    key: value
                    for key, value in headers.items()
                    if isinstance(key, str)
                    and key.lower() in allowed_header_names
                    and isinstance(value, str | int | float | bool | type(None))
                }
                if allowlisted_headers:
                    details["headers"] = allowlisted_headers

            return RateLimitExceededError(
                message=message,
                details=details,
                reset_at=reset_at,
            )

        http_message: str | None = None
        if isinstance(detail_payload, dict):
            http_message = detail_payload.get("message")
            if not http_message:
                error_block = detail_payload.get("error")
                if isinstance(error_block, dict):
                    http_message = error_block.get("message")
        elif detail_payload is not None:
            http_message = str(detail_payload)

        http_message = http_message or "Backend request failed"
        serialized_http_detail: Any
        if isinstance(
            detail_payload,
            dict | list | tuple | str | int | float | bool | type(None),
        ):
            serialized_http_detail = detail_payload
        else:
            serialized_http_detail = str(detail_payload)

        http_details: dict[str, Any] = {
            "backend": backend_type,
            "detail": serialized_http_detail,
            "status_code": status_code,
        }

        if 400 <= status_code < 500:
            # Preserve status_code for InvalidRequestError (especially important for 401)
            return InvalidRequestError(
                message=http_message,
                details=http_details,
                status_code=status_code,
            )

        return BackendError(
            message=http_message,
            backend_name=backend_type,
            status_code=status_code,
            details=http_details,
        )
