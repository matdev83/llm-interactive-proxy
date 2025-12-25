"""
Unit tests for Codebuff exception handling.

Tests exception creation, error response formatting, and error propagation.
Requirements: 10.4
"""

from __future__ import annotations

import pytest
from src.codebuff.exceptions import (
    CodebuffAuthenticationError,
    CodebuffConnectionError,
    CodebuffError,
    CodebuffMessageError,
    CodebuffSessionError,
    CodebuffValidationError,
    format_error_response,
)
from src.core.common.exceptions import LLMProxyError, ValidationError


class TestExceptionCreation:
    """Test exception creation with various parameters."""

    def test_codebuff_error_creation(self) -> None:
        """Test creating a basic CodebuffError."""
        error = CodebuffError(message="Test error", details={"key": "value"})

        assert error.message == "Test error"
        assert error.details == {"key": "value"}
        assert error.status_code == 500
        assert isinstance(error, LLMProxyError)

    def test_codebuff_connection_error_with_session_id(self) -> None:
        """Test creating a CodebuffConnectionError with session ID."""
        error = CodebuffConnectionError(
            message="Connection failed", session_id="session-123"
        )

        assert error.message == "Connection failed"
        assert error.session_id == "session-123"
        assert error.details["session_id"] == "session-123"
        assert isinstance(error, CodebuffError)

    def test_codebuff_message_error_with_message_type(self) -> None:
        """Test creating a CodebuffMessageError with message type."""
        error = CodebuffMessageError(message="Invalid message", message_type="prompt")

        assert error.message == "Invalid message"
        assert error.message_type == "prompt"
        assert error.details["message_type"] == "prompt"
        assert error.status_code == 400

    def test_codebuff_validation_error_with_validation_errors(self) -> None:
        """Test creating a CodebuffValidationError with validation errors."""
        validation_errors = [
            {"field": "promptId", "error": "required"},
            {"field": "model", "error": "invalid"},
        ]
        error = CodebuffValidationError(
            message="Validation failed",
            message_type="prompt",
            validation_errors=validation_errors,
        )

        assert error.message == "Validation failed"
        assert error.message_type == "prompt"
        assert error.validation_errors == validation_errors
        assert error.details["validation_errors"] == validation_errors
        assert isinstance(error, ValidationError)

    def test_codebuff_authentication_error_with_fingerprint(self) -> None:
        """Test creating a CodebuffAuthenticationError with fingerprint ID."""
        error = CodebuffAuthenticationError(
            message="Auth failed", fingerprint_id="fp-123"
        )

        assert error.message == "Auth failed"
        assert error.fingerprint_id == "fp-123"
        assert error.details["fingerprint_id"] == "fp-123"
        assert error.status_code == 401

    def test_codebuff_session_error_with_session_id(self) -> None:
        """Test creating a CodebuffSessionError with session ID."""
        error = CodebuffSessionError(
            message="Session not found", session_id="session-456"
        )

        assert error.message == "Session not found"
        assert error.session_id == "session-456"
        assert error.details["session_id"] == "session-456"
        assert error.status_code == 400


class TestErrorResponseFormatting:
    """Test error response formatting for Codebuff protocol."""

    def test_format_validation_error_as_ack(self) -> None:
        """Test formatting a validation error as an ack message."""
        error = CodebuffValidationError(
            message="Invalid prompt format", message_type="prompt"
        )
        response_model = format_error_response(error, txid=123)
        response = response_model.model_dump()

        assert response["type"] == "ack"
        assert response["txid"] == 123
        assert response["success"] is False
        assert response["error"] == "Invalid prompt format"

    def test_format_error_as_prompt_error_with_user_input_id(self) -> None:
        """Test formatting an error as a prompt-error action."""
        error = CodebuffError(message="Backend unavailable")
        response_model = format_error_response(error, user_input_id="prompt-123")
        response = response_model.model_dump(by_alias=True)

        assert response["type"] == "action"
        assert response["data"]["type"] == "prompt-error"
        assert response["data"]["userInputId"] == "prompt-123"
        assert response["data"]["message"] == "Backend unavailable"
        assert response["data"]["remainingBalance"] == 0.0

    def test_format_error_as_action_error(self) -> None:
        """Test formatting an error as a general action-error."""
        error = CodebuffSessionError(
            message="Session not found", session_id="session-789"
        )
        response_model = format_error_response(error)
        response = response_model.model_dump()

        assert response["type"] == "action"
        assert response["data"]["type"] == "action-error"
        assert response["data"]["message"] == "Session not found"
        assert response["data"]["remainingBalance"] == 0.0

    def test_format_generic_exception(self) -> None:
        """Test formatting a generic Python exception."""
        error = ValueError("Something went wrong")
        response_model = format_error_response(error)
        response = response_model.model_dump()

        assert response["type"] == "action"
        assert response["data"]["type"] == "action-error"
        assert response["data"]["message"] == "Something went wrong"

    def test_format_error_with_details(self) -> None:
        """Test formatting an error with details."""
        error = CodebuffError(message="Operation failed", details={"reason": "timeout"})
        response_model = format_error_response(error, user_input_id="prompt-456")
        response = response_model.model_dump()

        assert response["type"] == "action"
        assert response["data"]["type"] == "prompt-error"
        assert response["data"]["error"] == "{'reason': 'timeout'}"


class TestErrorPropagation:
    """Test error propagation through exception hierarchy."""

    def test_catch_codebuff_error_as_llm_proxy_error(self) -> None:
        """Test that CodebuffError can be caught as LLMProxyError."""
        with pytest.raises(LLMProxyError) as exc_info:
            raise CodebuffError("Test error")

        assert isinstance(exc_info.value, CodebuffError)
        assert exc_info.value.message == "Test error"

    def test_catch_codebuff_connection_error_as_codebuff_error(self) -> None:
        """Test that CodebuffConnectionError can be caught as CodebuffError."""
        with pytest.raises(CodebuffError) as exc_info:
            raise CodebuffConnectionError("Connection failed", session_id="s-123")

        assert isinstance(exc_info.value, CodebuffConnectionError)
        assert exc_info.value.session_id == "s-123"

    def test_catch_codebuff_validation_error_as_validation_error(self) -> None:
        """Test that CodebuffValidationError can be caught as ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            raise CodebuffValidationError("Validation failed")

        assert isinstance(exc_info.value, CodebuffValidationError)

    def test_exception_to_dict_includes_all_attributes(self) -> None:
        """Test that to_dict includes all exception attributes."""
        error = CodebuffConnectionError(message="Connection failed", session_id="s-456")
        error_dict = error.to_dict()

        assert "error" in error_dict
        assert error_dict["error"]["message"] == "Connection failed"
        assert error_dict["error"]["type"] == "CodebuffConnectionError"
        assert "session_id" in error_dict["error"]

    def test_exception_with_custom_status_code(self) -> None:
        """Test creating an exception with a custom status code."""
        error = CodebuffError(message="Custom error", status_code=503)

        assert error.status_code == 503

    def test_exception_details_are_referenced(self) -> None:
        """Test that exception details are referenced, not copied."""
        original_details = {"key": "value"}
        error = CodebuffError(message="Test", details=original_details)

        # Modify original details
        original_details["key"] = "modified"

        # Exception details should be affected (they share the same reference)
        assert error.details["key"] == "modified"
