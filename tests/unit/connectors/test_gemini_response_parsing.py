"""Unit tests for Gemini Code Assist response parsing helpers."""

import pytest
from src.connectors.gemini_base.graceful_degradation import is_rate_limit_like_error
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.common.exceptions import BackendError


def test_extract_generated_text_success() -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "Hello"}, {"text": " world"}]}},
        ]
    }

    text = GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert text == "Hello world"


def test_extract_generated_text_nested_candidates() -> None:
    payload = [
        {
            "result": {
                "response": {
                    "candidates": [
                        {"content": {"parts": [{"text": "Nested response"}]}},
                    ]
                }
            }
        }
    ]

    text = GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert text == "Nested response"


def test_extract_generated_text_raises_on_error_payload() -> None:
    payload = {"error": {"message": "Resource exhausted", "code": 429}}

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "gemini_error_payload"
    assert excinfo.value.status_code == 429


def test_extract_generated_text_raises_when_candidates_empty() -> None:
    payload = {"candidates": []}

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "empty_response"
    assert excinfo.value.status_code == 502


def test_extract_generated_text_handles_error_in_list_payload() -> None:
    payload = [
        {"error": {"message": "quota exceeded"}},
        {"candidates": []},
    ]

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "gemini_error_payload"
    assert excinfo.value.status_code == 429


def test_extract_generated_text_detects_nested_error() -> None:
    payload = [
        {
            "result": {
                "error": {
                    "message": "Resource exhausted",
                    "code": 429,
                }
            }
        }
    ]

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "gemini_error_payload"
    assert excinfo.value.status_code == 429


def test_extract_generated_text_empty_candidates_without_error() -> None:
    payload = [
        {"candidates": []},
    ]

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "empty_response"
    assert excinfo.value.status_code == 502


def test_is_rate_limit_like_error_handles_empty_response() -> None:
    """Test that empty_response code triggers rate limit handling."""
    err = BackendError(
        message="Empty response",
        code="empty_response",
        status_code=502,
    )
    # Use module-level function directly for testing
    assert is_rate_limit_like_error(err) is True


def test_is_rate_limit_like_error_handles_429() -> None:
    """Test that 429 status code triggers rate limit handling."""
    err = BackendError(
        message="Rate limited",
        code="rate_limit_exceeded",
        status_code=429,
    )
    # Use module-level function directly for testing
    assert is_rate_limit_like_error(err) is True


def test_is_rate_limit_like_error_other_errors_false() -> None:
    """Test that other error types don't trigger rate limit handling."""
    err = BackendError(
        message="Other failure",
        code="other",
        status_code=500,
    )
    # Use module-level function directly for testing
    assert is_rate_limit_like_error(err) is False
