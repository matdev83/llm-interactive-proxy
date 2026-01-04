"""
Custom exceptions for Codebuff backend compatibility.

All Codebuff exceptions inherit from the existing LLMProxyError hierarchy
to maintain consistency with the rest of the application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.common.exceptions import (
    AuthenticationError,
    LLMProxyError,
    ValidationError,
)

if TYPE_CHECKING:
    from src.codebuff.schemas import ServerMessage


class CodebuffError(LLMProxyError):
    """Base exception for all Codebuff-related errors."""

    def __init__(
        self,
        message: str = "Codebuff operation failed",
        details: dict | None = None,
        **kwargs,
    ):
        # Set default status_code if not provided
        if "status_code" not in kwargs:
            kwargs["status_code"] = 500
        super().__init__(message, details, **kwargs)


class CodebuffConnectionError(CodebuffError):
    """Raised when WebSocket connection operations fail."""

    def __init__(
        self,
        message: str = "WebSocket connection error",
        session_id: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        det = details.copy() if details else {}
        if session_id:
            det["session_id"] = session_id
        super().__init__(message, det, **kwargs)
        self.session_id = session_id


class CodebuffMessageError(CodebuffError):
    """Raised when message processing fails."""

    def __init__(
        self,
        message: str = "Message processing error",
        message_type: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        det = details.copy() if details else {}
        if message_type:
            det["message_type"] = message_type
        # Override status_code in kwargs if not already set
        if "status_code" not in kwargs:
            kwargs["status_code"] = 400
        super().__init__(message, det, **kwargs)
        self.message_type = message_type


class CodebuffValidationError(ValidationError):
    """Raised when Codebuff message validation fails."""

    def __init__(
        self,
        message: str = "Message validation failed",
        message_type: str | None = None,
        validation_errors: list | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        det = details.copy() if details else {}
        if message_type:
            det["message_type"] = message_type
        if validation_errors:
            det["validation_errors"] = validation_errors
        super().__init__(message, det, **kwargs)
        self.message_type = message_type
        self.validation_errors = validation_errors


class CodebuffAuthenticationError(AuthenticationError):
    """Raised when Codebuff authentication fails."""

    def __init__(
        self,
        message: str = "Codebuff authentication failed",
        fingerprint_id: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        det = details.copy() if details else {}
        if fingerprint_id:
            det["fingerprint_id"] = fingerprint_id
        super().__init__(message, det, **kwargs)
        self.fingerprint_id = fingerprint_id


class CodebuffSessionError(CodebuffError):
    """Raised when session operations fail."""

    def __init__(
        self,
        message: str = "Session operation failed",
        session_id: str | None = None,
        details: dict | None = None,
        **kwargs,
    ):
        det = details.copy() if details else {}
        if session_id:
            det["session_id"] = session_id
        # Override status_code in kwargs if not already set
        if "status_code" not in kwargs:
            kwargs["status_code"] = 400
        super().__init__(message, det, **kwargs)
        self.session_id = session_id


def format_error_response(
    error: Exception,
    txid: int | None = None,
    user_input_id: str | None = None,
) -> ServerMessage:
    """
    Format an exception into a Codebuff error response.

    Args:
        error: The exception to format
        txid: Optional transaction ID for ack messages
        user_input_id: Optional user input ID for prompt errors

    Returns:
        A model representing the error response in Codebuff format
    """
    from src.codebuff.schemas import (
        AckMessage,
        ActionErrorAction,
        PromptErrorAction,
        ServerActionMessage,
    )

    # Determine error message
    if isinstance(error, LLMProxyError):
        error_message = error.message
        error_details = str(error.details) if error.details else None
    else:
        error_message = str(error)
        error_details = None

    # For validation errors and message errors with txid, return ack with success=false
    if isinstance(
        error, CodebuffValidationError | CodebuffMessageError | ValidationError
    ) or (txid is not None and not user_input_id):
        return AckMessage(
            type="ack",
            txid=txid,
            success=False,
            error=error_message,
        )

    # For prompt-related errors with user_input_id, return prompt-error action
    if user_input_id:
        return ServerActionMessage(
            type="action",
            data=PromptErrorAction(
                type="prompt-error",
                userInputId=user_input_id,
                message=error_message,
                error=error_details,
                remainingBalance=0.0,
            ),
        )

    # For general action errors, return action-error
    return ServerActionMessage(
        type="action",
        data=ActionErrorAction(
            type="action-error",
            message=error_message,
            error=error_details,
            remainingBalance=0.0,
        ),
    )
