"""
Property-based tests for Codebuff exception hierarchy.

Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
Validates: Requirements 10.4
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from src.codebuff.exceptions import (
    CodebuffAuthenticationError,
    CodebuffConnectionError,
    CodebuffError,
    CodebuffMessageError,
    CodebuffSessionError,
    CodebuffValidationError,
)
from src.core.common.exceptions import (
    AuthenticationError,
    LLMProxyError,
    ValidationError,
)


@given(
    message=st.text(min_size=1, max_size=100),
    session_id=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_error_inherits_from_llm_proxy_error(
    message: str, session_id: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffError instance, it should inherit from LLMProxyError.
    """
    error = CodebuffError(message=message, details={"session_id": session_id})

    # Verify inheritance
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffError)

    # Verify attributes
    assert error.message == message
    assert hasattr(error, "details")
    assert hasattr(error, "status_code")


@given(
    message=st.text(min_size=1, max_size=100),
    session_id=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_connection_error_inherits_from_codebuff_error(
    message: str, session_id: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffConnectionError instance, it should inherit from CodebuffError.
    """
    error = CodebuffConnectionError(message=message, session_id=session_id)

    # Verify inheritance chain
    assert isinstance(error, CodebuffError)
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffConnectionError)

    # Verify session_id is stored
    if session_id:
        assert error.session_id == session_id
        assert error.details.get("session_id") == session_id


@given(
    message=st.text(min_size=1, max_size=100),
    message_type=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_message_error_inherits_from_codebuff_error(
    message: str, message_type: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffMessageError instance, it should inherit from CodebuffError.
    """
    error = CodebuffMessageError(message=message, message_type=message_type)

    # Verify inheritance chain
    assert isinstance(error, CodebuffError)
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffMessageError)

    # Verify message_type is stored
    if message_type:
        assert error.message_type == message_type
        assert error.details.get("message_type") == message_type


@given(
    message=st.text(min_size=1, max_size=100),
    message_type=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_validation_error_inherits_from_validation_error(
    message: str, message_type: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffValidationError instance, it should inherit from ValidationError.
    """
    error = CodebuffValidationError(message=message, message_type=message_type)

    # Verify inheritance chain
    assert isinstance(error, ValidationError)
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffValidationError)

    # Verify message_type is stored
    if message_type:
        assert error.message_type == message_type
        assert error.details.get("message_type") == message_type


@given(
    message=st.text(min_size=1, max_size=100),
    fingerprint_id=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_authentication_error_inherits_from_authentication_error(
    message: str, fingerprint_id: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffAuthenticationError instance, it should inherit from AuthenticationError.
    """
    error = CodebuffAuthenticationError(message=message, fingerprint_id=fingerprint_id)

    # Verify inheritance chain
    assert isinstance(error, AuthenticationError)
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffAuthenticationError)

    # Verify fingerprint_id is stored
    if fingerprint_id:
        assert error.fingerprint_id == fingerprint_id
        assert error.details.get("fingerprint_id") == fingerprint_id


@given(
    message=st.text(min_size=1, max_size=100),
    session_id=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
)
def test_codebuff_session_error_inherits_from_codebuff_error(
    message: str, session_id: str | None
) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any CodebuffSessionError instance, it should inherit from CodebuffError.
    """
    error = CodebuffSessionError(message=message, session_id=session_id)

    # Verify inheritance chain
    assert isinstance(error, CodebuffError)
    assert isinstance(error, LLMProxyError)
    assert isinstance(error, CodebuffSessionError)

    # Verify session_id is stored
    if session_id:
        assert error.session_id == session_id
        assert error.details.get("session_id") == session_id


@given(
    message=st.text(min_size=1, max_size=100),
)
def test_all_codebuff_errors_have_to_dict_method(message: str) -> None:
    """
    Feature: codebuff-backend-compatibility, Property 34: Exception hierarchy usage
    Validates: Requirements 10.4

    For any Codebuff exception, it should have a to_dict method inherited from LLMProxyError.
    """
    errors = [
        CodebuffError(message=message),
        CodebuffConnectionError(message=message),
        CodebuffMessageError(message=message),
        CodebuffValidationError(message=message),
        CodebuffAuthenticationError(message=message),
        CodebuffSessionError(message=message),
    ]

    for error in errors:
        # Verify to_dict method exists and returns a dict
        assert hasattr(error, "to_dict")
        error_dict = error.to_dict()
        assert isinstance(error_dict, dict)
        assert "error" in error_dict
        assert "message" in error_dict["error"]
        assert "type" in error_dict["error"]
        assert error_dict["error"]["message"] == message
