from __future__ import annotations

from typing import Any


class LLMProxyError(Exception):
    """Base exception for the LLM proxy."""

    def __init__(
        self,
        message: str = "",
        code: str | None = None,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a dictionary for serialization."""
        result: dict[str, Any] = {
            "error": {
                "message": self.message,
                "type": self.__class__.__name__,
                "code": self.code,
            }
        }
        if self.details:
            result["error"]["details"] = self.details
        return result


class BackendError(LLMProxyError):
    """Exception raised when a backend operation fails."""

    def __init__(
        self,
        message: str = "Backend operation failed",
        code: str | None = "backend_error",
        status_code: int = 500,
        backend_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=status_code, details=details
        )
        self.backend_name = backend_name

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a dictionary for serialization."""
        result = super().to_dict()
        if self.backend_name:
            result["error"]["backend"] = self.backend_name
        if self.details:
            result["error"]["details"] = self.details
        return result


class AuthenticationError(LLMProxyError):
    """Exception raised when authentication fails."""

    def __init__(
        self, message: str = "Authentication failed", code: str | None = "auth_error"
    ):
        super().__init__(message=message, code=code, status_code=401)


class ConfigurationError(LLMProxyError):
    """Exception raised when configuration is invalid or missing."""

    def __init__(
        self,
        message: str = "Configuration error",
        code: str | None = "config_error",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400, details=details)

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a dictionary for serialization."""
        result = super().to_dict()
        if self.details:
            result["details"] = self.details
        return result


class RateLimitExceededError(LLMProxyError):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        code: str | None = "rate_limit_exceeded",
        reset_at: float | None = None,
        limit: int | None = None,
        remaining: int | None = None,
    ):
        super().__init__(message=message, code=code, status_code=429)
        self.reset_at = reset_at
        self.limit = limit
        self.remaining = remaining

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a dictionary for serialization."""
        result = super().to_dict()
        if self.reset_at is not None:
            result["error"]["reset_at"] = self.reset_at
        if self.limit is not None:
            result["error"]["limit"] = self.limit
        if self.remaining is not None:
            result["error"]["remaining"] = self.remaining
        return result


class ServiceUnavailableError(LLMProxyError):
    """Exception raised when a backend service is unavailable."""

    def __init__(
        self,
        message: str = "Service unavailable",
        code: str | None = "service_unavailable",
    ):
        super().__init__(message=message, code=code, status_code=503)


class LoopDetectionError(LLMProxyError):
    """Exception raised when a loop is detected."""

    def __init__(
        self,
        message: str = "Loop detected",
        code: str | None = "loop_detected",
        pattern: str | None = None,
        repetitions: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400)
        self.pattern = pattern
        self.repetitions = repetitions
        self.details = details


class InvalidRequestError(LLMProxyError):
    """Error raised when a request is invalid."""

    def __init__(
        self,
        message: str,
        param: str | None = None,
        code: str | None = "invalid_request",
        details: dict[str, Any] | None = None,
    ):
        """Initialize the error.

        Args:
            message: The error message
            param: The parameter that caused the error
            code: An error code
            details: Additional details about the error
        """
        super().__init__(message=message, code=code, status_code=400)
        self.param = param
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Convert the error to a dictionary representation.

        Returns:
            A dictionary representation of the error
        """
        result = super().to_dict()

        if self.param:
            result["error"]["param"] = self.param

        if self.details:
            result["error"]["details"] = self.details

        return result


class ToolCallLoopError(LLMProxyError):
    """Exception raised when a tool call loop is detected."""

    def __init__(
        self,
        message: str = "Tool call loop detected",
        code: str | None = "tool_call_loop",
        pattern: str | None = None,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize the error.

        Args:
            message: The error message
            code: An error code
            pattern: The detected loop pattern
            tool_name: The tool that caused the loop
            details: Additional details about the error
        """
        super().__init__(message=message, code=code, status_code=400)
        self.pattern = pattern
        self.tool_name = tool_name
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """Convert the error to a dictionary representation.

        Returns:
            A dictionary representation of the error
        """
        result = super().to_dict()

        if self.pattern:
            result["error"]["pattern"] = self.pattern

        if self.tool_name:
            result["error"]["tool_name"] = self.tool_name

        return result


class InitializationError(LLMProxyError):
    """Exception raised during application initialization."""

    def __init__(
        self,
        message: str = "Application initialization failed",
        code: str | None = "initialization_error",
    ):
        super().__init__(message=message, code=code, status_code=500)


class StateError(LLMProxyError):
    """Exception raised for issues with application state management."""

    def __init__(
        self,
        message: str = "Application state error",
        code: str | None = "state_error",
    ):
        super().__init__(message=message, code=code, status_code=500)


class APIConnectionError(BackendError):
    """Exception raised when there's an issue connecting to a backend API."""

    def __init__(
        self,
        message: str = "Failed to connect to API",
        code: str | None = "api_connection_error",
        backend_name: str | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=503, backend_name=backend_name
        )


class APITimeoutError(BackendError):
    """Exception raised when an API call times out."""

    def __init__(
        self,
        message: str = "API call timed out",
        code: str | None = "api_timeout_error",
        backend_name: str | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=504, backend_name=backend_name
        )


class ModelNotFoundError(BackendError):
    """Exception raised when a requested model is not found on the backend."""

    def __init__(
        self,
        message: str = "Model not found",
        code: str | None = "model_not_found",
        backend_name: str | None = None,
        model_name: str | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=404, backend_name=backend_name
        )
        self.model_name = model_name

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.model_name:
            result["error"]["model_name"] = self.model_name
        return result


class ParsingError(LLMProxyError):
    """Base exception for errors during data parsing."""

    def __init__(
        self,
        message: str = "Data parsing error",
        code: str | None = "parsing_error",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=status_code, details=details
        )


class JSONParsingError(ParsingError):
    """Exception raised for errors during JSON parsing."""

    def __init__(
        self,
        message: str = "JSON parsing error",
        code: str | None = "json_parsing_error",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400, details=details)


class ToolCallParsingError(ParsingError):
    """Exception raised for errors during tool call parsing."""

    def __init__(
        self,
        message: str = "Tool call parsing error",
        code: str | None = "tool_call_parsing_error",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400, details=details)


class CommandError(LLMProxyError):
    """Base exception for errors related to command processing."""

    def __init__(
        self,
        message: str = "Command error",
        code: str | None = "command_error",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message, code=code, status_code=status_code, details=details
        )


class CommandExecutionError(CommandError):
    """Exception raised when a command fails to execute."""

    def __init__(
        self,
        message: str = "Command execution failed",
        code: str | None = "command_execution_error",
        command_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400, details=details)
        self.command_name = command_name

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.command_name:
            result["error"]["command_name"] = self.command_name
        return result


class InvalidArgumentError(CommandError):
    """Exception raised when a command receives an invalid argument."""

    def __init__(
        self,
        message: str = "Invalid argument",
        code: str | None = "invalid_argument",
        command_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=400, details=details)
        self.command_name = command_name

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.command_name:
            result["error"]["command_name"] = self.command_name
        return result


class CommandCreationError(CommandError):
    """Exception raised when a command fails to be created."""

    def __init__(
        self,
        message: str = "Command creation failed",
        code: str | None = "command_creation_error",
        command_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code, status_code=500, details=details)
        self.command_name = command_name

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.command_name:
            result["error"]["command_name"] = self.command_name
        return result


class ServiceResolutionError(StateError):
    """Exception raised when a service cannot be resolved from the container."""

    def __init__(
        self,
        message: str = "Service resolution failed",
        code: str | None = "service_resolution_error",
        service_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message=message, code=code)
        self.service_name = service_name

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.service_name:
            result["error"]["service_name"] = self.service_name
        return result
