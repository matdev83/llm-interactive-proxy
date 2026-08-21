"""
Common exception classes for the LLM Interactive Proxy.

This module defines custom exception classes used throughout the application
for better error handling and categorization.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.client_termination import ClientTerminationReason
    from src.core.domain.session_key import SessionKey


def _is_json_scalar(value: Any) -> bool:
    return isinstance(value, str | int | float | bool) or value is None


def _to_json_safe_error_value(value: Any) -> Any:
    if _is_json_scalar(value):
        return value
    if isinstance(value, dict):
        return {
            str(key): _to_json_safe_error_value(nested_value)
            for key, nested_value in value.items()
            if isinstance(key, str | int | float | bool)
        }
    if isinstance(value, list | tuple | set):
        return [_to_json_safe_error_value(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_json_safe_error_value(model_dump(mode="json"))

    return str(value)


class LLMProxyError(Exception):
    """Base exception class for all LLM proxy errors."""

    __resilience_context__: dict[str, Any] | None

    def __init__(
        self,
        message: str,
        details: dict | None = None,
        *,
        status_code: int | None = None,
        **kwargs,
    ):
        """Initialize the exception.

        Args:
            message: Human-readable error message
            details: Optional dictionary with additional error details
            status_code: Optional HTTP status code hint for transport adapters
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.status_code = status_code or 500
        self.__resilience_context__ = None
        # Attach any extra attributes provided for compatibility with callers/tests
        for key, value in (kwargs or {}).items():
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        error_dict: dict[str, Any] = {
            "message": self.message,
            "type": self.__class__.__name__,
            "details": _to_json_safe_error_value(self.details),
        }

        # Include any additional attributes that were set via kwargs
        for attr_name in dir(self):
            if (
                not attr_name.startswith("_")
                and attr_name not in ["message", "details", "status_code", "args"]
                and not callable(getattr(self, attr_name))
            ):
                error_dict[attr_name] = _to_json_safe_error_value(
                    getattr(self, attr_name)
                )

        return {"error": error_dict}


class AuthenticationError(LLMProxyError):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=401, **kwargs)


class BackendError(LLMProxyError):
    """Raised when a backend operation fails."""

    def __init__(
        self,
        message: str = "Backend operation failed",
        backend_name: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        # let adapters map to 502 by default unless overridden
        status_code = kwargs.pop("status_code", 502)
        self.code: str | None = kwargs.get("code")
        super().__init__(message, details, status_code=status_code, **kwargs)
        self.backend_name = backend_name


class ServiceUnavailableError(BackendError):
    """Raised when a service is temporarily unavailable."""

    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details=details, status_code=503, **kwargs)


class ConfigurationError(LLMProxyError):
    """Raised when there's a configuration issue."""

    def __init__(
        self,
        message: str = "Configuration error",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class RateLimitExceededError(BackendError):
    """Raised when rate limits are exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: dict | None = None,
        **kwargs,
    ):
        reset_at = kwargs.pop("reset_at", None)
        super().__init__(
            message, details=details, status_code=429, reset_at=reset_at, **kwargs
        )
        # optional reset time in seconds for Retry-After
        self.reset_at: int | None = reset_at


class ValidationError(LLMProxyError):
    """Raised when validation fails."""

    def __init__(
        self, message: str = "Validation failed", details: dict | None = None, **kwargs
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class InvalidRequestError(LLMProxyError):
    """Raised when a request is invalid."""

    def __init__(
        self, message: str = "Invalid request", details: dict | None = None, **kwargs
    ):
        # Preserve status_code from kwargs if provided (e.g., 401 for auth failures)
        status_code = kwargs.pop("status_code", 400)
        super().__init__(message, details, status_code=status_code, **kwargs)


class ServiceResolutionError(LLMProxyError):
    """Raised when service resolution fails in DI container."""

    def __init__(
        self,
        message: str = "Service resolution failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=500, **kwargs)


class LoopDetectionError(LLMProxyError):
    """Raised when a loop is detected in responses."""

    def __init__(
        self,
        message: str = "Loop detected in response",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class TranslationError(LLMProxyError):
    """Raised when translation between API formats fails."""

    def __init__(
        self,
        message: str = "Translation failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(
            message, details, status_code=422, **kwargs
        )  # 422 for Unprocessable Entity


class ParsingError(LLMProxyError):
    """Raised when parsing fails."""

    def __init__(
        self, message: str = "Parsing failed", details: dict | None = None, **kwargs
    ):
        super().__init__(message, details, status_code=422, **kwargs)


class QualityVerifierError(LLMProxyError):
    """Raised when Quality Verifier cannot complete."""

    def __init__(
        self,
        message: str = "Quality Verifier failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=500, **kwargs)


# Additional exceptions referenced across the codebase


class LoopBreakingError(LLMProxyError):
    """Raised when loop breaking is triggered and need to handle retry flow."""

    def __init__(
        self,
        message: str = "Loop detected and breaking initiated",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(
            message, details, status_code=200, **kwargs
        )  # 200 OK, but with loop breaking metadata


class InitializationError(LLMProxyError):
    def __init__(
        self,
        message: str = "Initialization failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=500, **kwargs)


class ToolCallReactorError(LLMProxyError):
    def __init__(
        self,
        message: str = "Tool call reactor error",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class ToolCallLoopError(LLMProxyError):
    def __init__(
        self,
        message: str = "Tool call loop detected",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class ToolCallParsingError(LLMProxyError):
    def __init__(
        self,
        message: str = "Tool call parsing error",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class JSONParsingError(ParsingError):
    def __init__(
        self,
        message: str = "JSON parsing failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, **kwargs)


class CommandCreationError(LLMProxyError):
    def __init__(
        self,
        message: str = "Failed to create command",
        command_name: str | None = None,
        details: dict | None = None,
    ):
        det = details.copy() if details else {}
        if command_name:
            det.setdefault("command_name", command_name)
        super().__init__(message, det, status_code=500)


class APIConnectionError(BackendError):
    def __init__(
        self,
        message: str = "API connection error",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, backend_name=None, details=details, **kwargs)


class APITimeoutError(BackendError):
    def __init__(
        self, message: str = "API timeout", details: dict | None = None, **kwargs
    ):
        super().__init__(message, backend_name=None, details=details, **kwargs)


class RoutingError(LLMProxyError):
    """Raised when routing fails due to policy restrictions or configuration issues."""

    def __init__(
        self,
        message: str = "Routing failed",
        details: dict | None = None,
        status_code: int | None = None,
        **kwargs,
    ):
        if status_code is None and isinstance(details, dict):
            code = details.get("code")
            if code == "unknown_model":
                status_code = 404
            elif code == "unsupported_on_instance":
                status_code = 400
            elif code == "temporarily_unavailable":
                status_code = 503
            elif code == "policy_rejected":
                status_code = 403
        if status_code is None:
            status_code = 503
        super().__init__(message, details, status_code=status_code, **kwargs)


class SessionCancelledError(LLMProxyError):
    """Raised when attempting to initiate work for a cancelled session.

    This exception is raised by the cancellation gate when a component attempts
    to initiate backend work (initial call, retry, failover, recovery, follow-up)
    for a session that has been cancelled due to client termination.

    Status code 499 (Client Closed Request) indicates the client terminated
    the connection before the server could complete the request.
    """

    def __init__(
        self,
        session_key: SessionKey | None = None,
        reason: ClientTerminationReason | None = None,
        message: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        """Initialize the exception.

        Args:
            session_key: The cancelled session identifier.
            reason: The client termination reason.
            message: Optional custom error message.
            details: Optional additional error details.
        """
        if message is None:
            if session_key:
                message = f"Session cancelled: {session_key.primary_id}"
            else:
                message = "Session cancelled"
        det = details.copy() if details else {}
        if session_key:
            det["session_key"] = {
                "protocol": session_key.protocol,
                "primary_id": session_key.primary_id,
                "group_id": session_key.group_id,
            }
        if reason:
            det["reason"] = reason.value
        super().__init__(message, det, status_code=499, **kwargs)
        self.session_key = session_key
        self.reason = reason


class DuplicateRequestError(BackendError):
    """Raised when a duplicate request is detected and swallowed.

    This error is raised by the request deduplication service when it detects
    that an identical request was sent within the configured dedup window.
    """

    def __init__(
        self,
        content_hash: str,
        session_id: str,
        message: str | None = None,
        details: dict | None = None,
        retry_after_seconds: float | None = None,
        **kwargs,
    ):
        self.content_hash = content_hash
        self.session_id = session_id
        if message is None:
            message = (
                f"Duplicate request detected (hash={content_hash[:8]}..., "
                f"session={session_id})"
            )
        det = details.copy() if details else {}
        det["content_hash"] = content_hash
        det["session_id"] = session_id
        if isinstance(retry_after_seconds, int | float) and retry_after_seconds > 0:
            retry_after = float(retry_after_seconds)
            det["retry_after"] = retry_after
            kwargs.setdefault("reset_at", time.time() + retry_after)
            self.retry_after_seconds = retry_after
        super().__init__(
            message, backend_name=None, details=det, status_code=429, **kwargs
        )


class NonForwardableEnforcementError(LLMProxyError):
    """Raised when internal error occurs during non-forwardable message enforcement.

    This error indicates a failure during identity computation, registry lookup,
    or filtering that prevents safe enforcement. The proxy must fail closed
    (not call any remote backend) when this error occurs.

    Status code 500 indicates an internal server error.
    """

    def __init__(
        self,
        message: str = "Non-forwardable enforcement failed",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=500, **kwargs)


class NoForwardableContentError(LLMProxyError):
    """Raised when filtering removes all forwardable user-provided content.

    This error is raised when non-forwardable filtering removes all messages
    that contain forwardable user-provided content, leaving nothing to send
    to the remote backend.

    Status code 400 indicates a bad request (nothing forwardable to send).
    """

    def __init__(
        self,
        message: str = "No forwardable content remains after filtering",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class NonForwardableTagLimitExceededError(LLMProxyError):
    """Raised when non-forwardable tag capacity limit is exceeded.

    This error is raised when tagging would exceed the configured per-session
    tag capacity limit. The proxy must fail closed (not call any remote backend)
    when this error occurs to prevent unbounded memory growth.

    Status code 400 indicates a bad request (tag capacity exceeded).
    """

    def __init__(
        self,
        message: str = "Non-forwardable tag capacity exceeded",
        session_id: str | None = None,
        max_limit: int | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        self.session_id = session_id
        self.max_limit = max_limit
        det = details.copy() if details else {}
        if session_id:
            det["session_id"] = session_id
        if max_limit:
            det["max_limit"] = max_limit
        super().__init__(message, det, status_code=400, **kwargs)


class ResponsesProtocolError(LLMProxyError):
    """Base for Responses API protocol errors (OpenAI-compatible codes and params)."""

    def __init__(
        self,
        message: str,
        code: str,
        param: str | None = None,
        status_code: int = 400,
        *,
        error_type: str = "invalid_request_error",
        details: dict | None = None,
        **kwargs,
    ) -> None:
        det = details.copy() if details else {}
        det.setdefault("code", code)
        if param is not None:
            det.setdefault("param", param)
        super().__init__(message, det, status_code=status_code, **kwargs)
        self.code = code
        self.param = param
        self.error_type = error_type


class ResponsesValidationError(ResponsesProtocolError):
    """Client request validation failure for the Responses API frontend."""

    def __init__(
        self,
        message: str,
        code: str = "invalid_request_error",
        param: str | None = None,
        status_code: int = 400,
        *,
        error_type: str = "invalid_request_error",
        details: dict | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            message,
            code,
            param=param,
            status_code=status_code,
            error_type=error_type,
            details=details,
            **kwargs,
        )


class ResponsesPreviousResponseNotFoundError(ResponsesProtocolError):
    """Raised when previous_response_id cannot be resolved in the session store."""

    def __init__(self, response_id: str) -> None:
        message = f"Previous response not found: {response_id}"
        super().__init__(
            message,
            code="previous_response_not_found",
            param="previous_response_id",
            status_code=400,
            details={"previous_response_id": response_id},
        )
        self.previous_response_id = response_id


class ResponsesProviderLimitationError(ResponsesProtocolError):
    """Requested feature cannot be preserved for the selected backend."""

    def __init__(self, feature: str, provider: str) -> None:
        message = f"Feature {feature!r} cannot be preserved for provider {provider!r}"
        super().__init__(
            message,
            code="provider_limitation",
            param=feature,
            status_code=400,
            details={"feature": feature, "provider": provider},
        )
        self.feature = feature
        self.provider = provider
