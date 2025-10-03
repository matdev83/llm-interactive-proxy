"""
Common exception classes for the LLM Interactive Proxy.

This module defines custom exception classes used throughout the application
for better error handling and categorization.
"""

from __future__ import annotations


class LLMProxyError(Exception):
    """Base exception class for all LLM proxy errors."""

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
        # Attach any extra attributes provided for compatibility with callers/tests
        for key, value in (kwargs or {}).items():
            setattr(self, key, value)

    def to_dict(self) -> dict:
        error_dict = {
            "message": self.message,
            "type": self.__class__.__name__,
            "details": self.details,
        }

        # Include any additional attributes that were set via kwargs
        for attr_name in dir(self):
            if (
                not attr_name.startswith("_")
                and attr_name not in ["message", "details", "status_code", "args"]
                and not callable(getattr(self, attr_name))
            ):
                error_dict[attr_name] = getattr(self, attr_name)

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
        super().__init__(message, details, status_code=status_code, **kwargs)
        self.backend_name = backend_name


class ServiceUnavailableError(LLMProxyError):
    """Raised when a service is temporarily unavailable."""

    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=503, **kwargs)


class ConfigurationError(LLMProxyError):
    """Raised when there's a configuration issue."""

    def __init__(
        self,
        message: str = "Configuration error",
        details: dict | None = None,
        **kwargs,
    ):
        super().__init__(message, details, status_code=400, **kwargs)


class RateLimitExceededError(LLMProxyError):
    """Raised when rate limits are exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: dict | None = None,
        **kwargs,
    ):
        reset_at = kwargs.pop("reset_at", None)
        super().__init__(message, details, status_code=429, reset_at=reset_at, **kwargs)
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
        super().__init__(message, details, status_code=400, **kwargs)


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


class ParsingError(LLMProxyError):
    """Raised when parsing fails."""

    def __init__(
        self, message: str = "Parsing failed", details: dict | None = None, **kwargs
    ):
        super().__init__(message, details, status_code=422, **kwargs)


# Additional exceptions referenced across the codebase


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
