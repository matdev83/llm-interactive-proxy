from __future__ import annotations

from typing import Any


class ProxyError(Exception):
    """Base class for all exceptions in the proxy."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            status_code: The HTTP status code
            details: Additional error details
        """
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a dictionary for API responses.

        Returns:
            Dictionary representation of the exception
        """
        result = {
            "error": {
                "message": self.message,
                "type": self.__class__.__name__,
                "status_code": self.status_code,
            }
        }

        if self.details:
            result["error"]["details"] = self.details

        return result


class ConfigurationError(ProxyError):
    """Exception raised for configuration errors."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            details: Additional error details
        """
        super().__init__(
            message=message,
            status_code=500,  # Internal Server Error
            details=details,
        )


class AuthenticationError(ProxyError):
    """Exception raised for authentication errors."""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            details: Additional error details
        """
        super().__init__(
            message=message,
            status_code=401,  # Unauthorized
            details=details,
        )


class RateLimitExceededError(ProxyError):
    """Exception raised when rate limits are exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        reset_at: float | None = None,
        limit: int | None = None,
        remaining: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            reset_at: When the rate limit will reset
            limit: The rate limit
            remaining: The remaining quota
            details: Additional error details
        """
        error_details = details or {}
        if reset_at is not None:
            error_details["reset_at"] = reset_at
        if limit is not None:
            error_details["limit"] = limit
        if remaining is not None:
            error_details["remaining"] = remaining

        super().__init__(
            message=message,
            status_code=429,  # Too Many Requests
            details=error_details,
        )


class BackendError(ProxyError):
    """Exception raised for backend API errors."""

    def __init__(
        self,
        message: str,
        backend: str | None = None,
        backend_status_code: int | None = None,
        backend_response: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            backend: The backend that raised the error
            backend_status_code: The status code returned by the backend
            backend_response: The raw response from the backend
            details: Additional error details
        """
        error_details = details or {}
        if backend is not None:
            error_details["backend"] = backend
        if backend_status_code is not None:
            error_details["backend_status_code"] = backend_status_code
        if backend_response is not None:
            error_details["backend_response"] = backend_response

        super().__init__(
            message=message,
            status_code=502,  # Bad Gateway
            details=error_details,
        )


class ValidationError(ProxyError):
    """Exception raised for validation errors."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            field: The field that failed validation
            details: Additional error details
        """
        error_details = details or {}
        if field is not None:
            error_details["field"] = field

        super().__init__(
            message=message,
            status_code=400,  # Bad Request
            details=error_details,
        )


class CommandError(ProxyError):
    """Exception raised for command execution errors."""

    def __init__(
        self,
        message: str,
        command: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            command: The command that failed
            details: Additional error details
        """
        error_details = details or {}
        if command is not None:
            error_details["command"] = command

        super().__init__(
            message=message,
            status_code=400,  # Bad Request
            details=error_details,
        )


class LoopDetectionError(ProxyError):
    """Exception raised when a loop is detected."""

    def __init__(
        self,
        message: str = "Response loop detected",
        pattern: str | None = None,
        repetitions: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            pattern: The repeating pattern detected
            repetitions: The number of repetitions detected
            details: Additional error details
        """
        error_details = details or {}
        if pattern is not None:
            # Truncate long patterns
            error_details["pattern"] = (
                pattern[:100] + "..." if len(pattern) > 100 else pattern
            )
        if repetitions is not None:
            error_details["repetitions"] = repetitions

        super().__init__(
            message=message,
            status_code=400,  # Bad Request
            details=error_details,
        )


class ToolCallLoopError(ProxyError):
    """Exception raised when a tool call loop is detected."""

    def __init__(
        self,
        message: str = "Tool call loop detected",
        tool_name: str | None = None,
        repetitions: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the exception.

        Args:
            message: The error message
            tool_name: The tool involved in the loop
            repetitions: The number of repetitions detected
            details: Additional error details
        """
        error_details = details or {}
        if tool_name is not None:
            error_details["tool_name"] = tool_name
        if repetitions is not None:
            error_details["repetitions"] = repetitions

        super().__init__(
            message=message,
            status_code=400,  # Bad Request
            details=error_details,
        )
