"""Unit tests for Gemini Code Assist response parsing helpers."""

import pytest
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


def test_extract_generated_text_raises_on_error_payload() -> None:
    payload = {"error": {"message": "Resource exhausted", "code": 429}}

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "gemini_error_payload"


def test_extract_generated_text_raises_when_candidates_empty() -> None:
    payload = {"candidates": []}

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "empty_response"


def test_extract_generated_text_handles_error_in_list_payload() -> None:
    payload = [
        {"error": {"message": "quota exceeded"}},
        {"candidates": []},
    ]

    with pytest.raises(BackendError) as excinfo:
        GeminiOAuthBaseConnector._extract_generated_text_from_response(payload)

    assert excinfo.value.code == "gemini_error_payload"
