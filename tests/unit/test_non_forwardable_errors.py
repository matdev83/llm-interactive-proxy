"""
Unit tests for non-forwardable message tagging error types.

Tests coverage for:
- NonForwardableEnforcementError: internal enforcement failures (fail closed)
- NoForwardableContentError: no forwardable content remains after filtering
- NonForwardableTagLimitExceededError: tag capacity exceeded

Requirements: 5.3, 6.2, 7.3, 10.1, 14.3
"""

from src.core.common.exceptions import (
    LLMProxyError,
    NoForwardableContentError,
    NonForwardableEnforcementError,
    NonForwardableTagLimitExceededError,
)


class TestNonForwardableEnforcementError:
    """Tests for NonForwardableEnforcementError."""

    def test_inherits_from_llm_proxy_error(self) -> None:
        """Error inherits from LLMProxyError."""
        error = NonForwardableEnforcementError("Test error")
        assert isinstance(error, LLMProxyError)

    def test_status_code_is_500(self) -> None:
        """Error has status code 500."""
        error = NonForwardableEnforcementError("Test error")
        assert error.status_code == 500

    def test_error_message(self) -> None:
        """Error preserves message."""
        message = "Internal enforcement failure"
        error = NonForwardableEnforcementError(message)
        assert error.message == message
        assert str(error) == message

    def test_error_details(self) -> None:
        """Error can include details."""
        details = {"session_id": "test_session", "reason": "lookup_failed"}
        error = NonForwardableEnforcementError("Test error", details=details)
        assert error.details == details

    def test_to_dict_structure(self) -> None:
        """Error serializes to dict correctly."""
        error = NonForwardableEnforcementError("Test error")
        error_dict = error.to_dict()
        assert "error" in error_dict
        assert error_dict["error"]["message"] == "Test error"
        assert error_dict["error"]["type"] == "NonForwardableEnforcementError"
        assert error_dict["error"]["details"] == {}


class TestNoForwardableContentError:
    """Tests for NoForwardableContentError."""

    def test_inherits_from_llm_proxy_error(self) -> None:
        """Error inherits from LLMProxyError."""
        error = NoForwardableContentError("No forwardable content")
        assert isinstance(error, LLMProxyError)

    def test_status_code_is_400(self) -> None:
        """Error has status code 400."""
        error = NoForwardableContentError("No forwardable content")
        assert error.status_code == 400

    def test_error_message(self) -> None:
        """Error preserves message."""
        message = "No forwardable content remains after filtering"
        error = NoForwardableContentError(message)
        assert error.message == message

    def test_error_does_not_leak_content(self) -> None:
        """Error message does not leak filtered message content."""
        # Error should not include actual message content in details
        error = NoForwardableContentError("No forwardable content")
        error_dict = error.to_dict()
        # Error dict should not contain actual message content fields like "role", "content", etc.
        # The word "content" in "No forwardable content" is acceptable as it's the error message itself
        # We're checking that details don't leak actual message content
        assert "details" in error_dict["error"]
        # Details should be empty or not contain message content fields
        details = error_dict["error"]["details"]
        # Should not have fields that would leak actual message content
        assert "role" not in details
        assert "tool_call_id" not in details
        # The error message itself can mention "content" as part of the error description

    def test_to_dict_structure(self) -> None:
        """Error serializes to dict correctly."""
        error = NoForwardableContentError("No forwardable content")
        error_dict = error.to_dict()
        assert "error" in error_dict
        assert error_dict["error"]["message"] == "No forwardable content"
        assert error_dict["error"]["type"] == "NoForwardableContentError"


class TestNonForwardableTagLimitExceededError:
    """Tests for NonForwardableTagLimitExceededError."""

    def test_inherits_from_llm_proxy_error(self) -> None:
        """Error inherits from LLMProxyError."""
        error = NonForwardableTagLimitExceededError(
            "Tag limit exceeded", session_id="test_session"
        )
        assert isinstance(error, LLMProxyError)

    def test_status_code_is_400(self) -> None:
        """Error has status code 400."""
        error = NonForwardableTagLimitExceededError(
            "Tag limit exceeded", session_id="test_session"
        )
        assert error.status_code == 400

    def test_error_message(self) -> None:
        """Error preserves message."""
        message = "Non-forwardable tag capacity exceeded"
        error = NonForwardableTagLimitExceededError(message, session_id="test_session")
        assert error.message == message

    def test_error_includes_session_context(self) -> None:
        """Error includes session context."""
        session_id = "test_session_123"
        error = NonForwardableTagLimitExceededError(
            "Tag limit exceeded", session_id=session_id, max_limit=10000
        )
        assert hasattr(error, "session_id")
        assert error.session_id == session_id
        assert hasattr(error, "max_limit")
        assert error.max_limit == 10000

    def test_error_details_include_session(self) -> None:
        """Error details include session information."""
        session_id = "test_session_123"
        error = NonForwardableTagLimitExceededError(
            "Tag limit exceeded", session_id=session_id, max_limit=10000
        )
        error_dict = error.to_dict()
        # Session info should be in details or as attribute
        assert session_id in str(error_dict) or hasattr(error, "session_id")

    def test_to_dict_structure(self) -> None:
        """Error serializes to dict correctly."""
        error = NonForwardableTagLimitExceededError(
            "Tag limit exceeded", session_id="test_session"
        )
        error_dict = error.to_dict()
        assert "error" in error_dict
        assert error_dict["error"]["message"] == "Tag limit exceeded"
        assert error_dict["error"]["type"] == "NonForwardableTagLimitExceededError"
