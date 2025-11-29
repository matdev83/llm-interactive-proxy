"""
Property-based tests for usage format translation.

This module contains property tests for:
- Property 7: Usage format translation (Requirements 4.2, 4.3)

These tests verify that Gemini's usageMetadata format is correctly converted
to OpenAI format, and that response adapters include usage in headers.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.translation import Translation
from src.core.transport.fastapi.response_adapters import (
    _apply_usage_headers,
    to_fastapi_response,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating Gemini usage metadata
# ============================================================================


@st.composite
def gemini_usage_metadata_strategy(draw: Any) -> dict[str, int]:
    """Generate valid Gemini usageMetadata dictionaries.

    Gemini format uses:
    - promptTokenCount
    - candidatesTokenCount
    - totalTokenCount
    """
    prompt_token_count = draw(st.integers(min_value=0, max_value=100000))
    candidates_token_count = draw(st.integers(min_value=0, max_value=100000))
    return {
        "promptTokenCount": prompt_token_count,
        "candidatesTokenCount": candidates_token_count,
        "totalTokenCount": prompt_token_count + candidates_token_count,
    }


@st.composite
def openai_usage_strategy(draw: Any) -> dict[str, int]:
    """Generate valid OpenAI usage dictionaries.

    OpenAI format uses:
    - prompt_tokens
    - completion_tokens
    - total_tokens
    """
    prompt_tokens = draw(st.integers(min_value=0, max_value=100000))
    completion_tokens = draw(st.integers(min_value=0, max_value=100000))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@st.composite
def gemini_response_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid Gemini response dictionaries with usageMetadata."""
    usage_metadata = draw(gemini_usage_metadata_strategy())

    # Generate text content
    text_content = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                blacklist_characters="\x00",
            ),
            min_size=0,
            max_size=200,
        )
    )

    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": text_content}],
                    "role": "model",
                },
                "finishReason": draw(
                    st.sampled_from(["STOP", "MAX_TOKENS", "SAFETY", None])
                ),
            }
        ],
        "usageMetadata": usage_metadata,
    }


@st.composite
def response_envelope_with_usage_strategy(draw: Any) -> ResponseEnvelope:
    """Generate ResponseEnvelope with usage data for testing headers."""
    usage = draw(openai_usage_strategy())

    # Generate simple content
    content_text = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=100,
        )
    )

    content = {
        "id": f"chatcmpl-{draw(st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', min_size=8, max_size=16))}",
        "object": "chat.completion",
        "created": draw(st.integers(min_value=1000000000, max_value=2000000000)),
        "model": draw(
            st.sampled_from(["gpt-4", "gpt-3.5-turbo", "gemini-pro", "claude-3-opus"])
        ),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content_text,
                },
                "finish_reason": "stop",
            }
        ],
    }

    return ResponseEnvelope(
        content=content,
        headers={"x-request-id": "test-request"},
        status_code=200,
        usage=usage,
    )


# ============================================================================
# Property 7: Usage format translation
# ============================================================================


@given(gemini_usage=gemini_usage_metadata_strategy())
@property_test_settings()
def test_property_7_gemini_to_openai_usage_translation(
    gemini_usage: dict[str, int],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.2**

    *For any* Gemini-format usage data (usageMetadata with promptTokenCount,
    candidatesTokenCount, totalTokenCount), the translation service SHALL
    convert it to OpenAI format (usage with prompt_tokens, completion_tokens,
    total_tokens).
    """
    # Use the internal normalization method
    openai_usage = Translation._normalize_usage_metadata(gemini_usage, "gemini")

    # Verify the conversion
    assert "prompt_tokens" in openai_usage, "OpenAI format must have prompt_tokens"
    assert (
        "completion_tokens" in openai_usage
    ), "OpenAI format must have completion_tokens"
    assert "total_tokens" in openai_usage, "OpenAI format must have total_tokens"

    # Verify values are correctly mapped
    assert openai_usage["prompt_tokens"] == gemini_usage["promptTokenCount"], (
        f"prompt_tokens mismatch: {openai_usage['prompt_tokens']} != "
        f"{gemini_usage['promptTokenCount']}"
    )
    assert openai_usage["completion_tokens"] == gemini_usage["candidatesTokenCount"], (
        f"completion_tokens mismatch: {openai_usage['completion_tokens']} != "
        f"{gemini_usage['candidatesTokenCount']}"
    )
    assert openai_usage["total_tokens"] == gemini_usage["totalTokenCount"], (
        f"total_tokens mismatch: {openai_usage['total_tokens']} != "
        f"{gemini_usage['totalTokenCount']}"
    )


@given(gemini_response=gemini_response_strategy())
@property_test_settings()
def test_property_7_gemini_response_usage_extraction(
    gemini_response: dict[str, Any],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.2**

    *For any* Gemini response with usageMetadata, the gemini_to_domain_response
    method SHALL extract and convert the usage data to OpenAI format.
    """
    # Convert Gemini response to domain response
    domain_response = Translation.gemini_to_domain_response(gemini_response)

    # Verify usage is present and in OpenAI format
    assert domain_response.usage is not None, "Domain response must have usage"
    assert "prompt_tokens" in domain_response.usage, "Usage must have prompt_tokens"
    assert (
        "completion_tokens" in domain_response.usage
    ), "Usage must have completion_tokens"
    assert "total_tokens" in domain_response.usage, "Usage must have total_tokens"

    # Verify values match the original Gemini usage
    original_usage = gemini_response["usageMetadata"]
    assert domain_response.usage["prompt_tokens"] == original_usage["promptTokenCount"]
    assert (
        domain_response.usage["completion_tokens"]
        == original_usage["candidatesTokenCount"]
    )
    assert domain_response.usage["total_tokens"] == original_usage["totalTokenCount"]


@given(usage=openai_usage_strategy())
@property_test_settings()
def test_property_7_usage_headers_applied(usage: dict[str, int]) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.3**

    *For any* OpenAI-format usage data, the response adapter SHALL include
    this data in x-usage-* headers.
    """
    # Apply usage headers
    headers = _apply_usage_headers({}, usage)

    # Verify headers are present
    assert "x-usage-prompt-tokens" in headers, "Must have x-usage-prompt-tokens header"
    assert (
        "x-usage-completion-tokens" in headers
    ), "Must have x-usage-completion-tokens header"
    assert "x-usage-total-tokens" in headers, "Must have x-usage-total-tokens header"

    # Verify header values match usage
    assert headers["x-usage-prompt-tokens"] == str(usage["prompt_tokens"]), (
        f"x-usage-prompt-tokens mismatch: {headers['x-usage-prompt-tokens']} != "
        f"{usage['prompt_tokens']}"
    )
    assert headers["x-usage-completion-tokens"] == str(usage["completion_tokens"]), (
        f"x-usage-completion-tokens mismatch: {headers['x-usage-completion-tokens']} != "
        f"{usage['completion_tokens']}"
    )
    assert headers["x-usage-total-tokens"] == str(usage["total_tokens"]), (
        f"x-usage-total-tokens mismatch: {headers['x-usage-total-tokens']} != "
        f"{usage['total_tokens']}"
    )


@given(envelope=response_envelope_with_usage_strategy())
@property_test_settings()
def test_property_7_response_adapter_includes_usage_in_body_and_headers(
    envelope: ResponseEnvelope,
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.3**

    *For any* ResponseEnvelope with usage data, the response adapter SHALL
    include usage data both in the response body and in x-usage-* headers.
    """
    # Convert to FastAPI response
    response = to_fastapi_response(envelope)

    # Parse response body
    body = json.loads(response.body)

    # Verify usage is in body
    assert "usage" in body, "Response body must contain usage"
    body_usage = body["usage"]
    assert "prompt_tokens" in body_usage, "Body usage must have prompt_tokens"
    assert "completion_tokens" in body_usage, "Body usage must have completion_tokens"
    assert "total_tokens" in body_usage, "Body usage must have total_tokens"

    # Verify usage headers are present
    assert (
        "x-usage-prompt-tokens" in response.headers
    ), "Response must have x-usage-prompt-tokens header"
    assert (
        "x-usage-completion-tokens" in response.headers
    ), "Response must have x-usage-completion-tokens header"
    assert (
        "x-usage-total-tokens" in response.headers
    ), "Response must have x-usage-total-tokens header"

    # Verify header values match body usage
    assert response.headers["x-usage-prompt-tokens"] == str(
        body_usage["prompt_tokens"]
    ), (
        f"Header/body prompt_tokens mismatch: "
        f"{response.headers['x-usage-prompt-tokens']} != {body_usage['prompt_tokens']}"
    )
    assert response.headers["x-usage-completion-tokens"] == str(
        body_usage["completion_tokens"]
    ), (
        f"Header/body completion_tokens mismatch: "
        f"{response.headers['x-usage-completion-tokens']} != "
        f"{body_usage['completion_tokens']}"
    )
    assert response.headers["x-usage-total-tokens"] == str(
        body_usage["total_tokens"]
    ), (
        f"Header/body total_tokens mismatch: "
        f"{response.headers['x-usage-total-tokens']} != {body_usage['total_tokens']}"
    )


@given(usage=openai_usage_strategy())
@property_test_settings()
def test_property_7_usage_headers_preserve_existing_headers(
    usage: dict[str, int],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.3**

    *For any* usage data, the _apply_usage_headers function SHALL preserve
    existing headers while adding usage headers.
    """
    # Start with some existing headers
    existing_headers = {
        "x-request-id": "test-123",
        "content-type": "application/json",
        "x-custom-header": "custom-value",
    }

    # Apply usage headers
    result_headers = _apply_usage_headers(existing_headers.copy(), usage)

    # Verify existing headers are preserved
    for key, value in existing_headers.items():
        assert key in result_headers, f"Existing header '{key}' must be preserved"
        assert (
            result_headers[key] == value
        ), f"Existing header '{key}' value changed: {result_headers[key]} != {value}"

    # Verify usage headers are added
    assert "x-usage-prompt-tokens" in result_headers
    assert "x-usage-completion-tokens" in result_headers
    assert "x-usage-total-tokens" in result_headers


@given(usage=openai_usage_strategy())
@property_test_settings()
def test_property_7_usage_headers_handle_none_headers(
    usage: dict[str, int],
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.3**

    *For any* usage data, the _apply_usage_headers function SHALL handle
    None headers gracefully and return a new dict with usage headers.
    """
    # Apply usage headers with None input
    result_headers = _apply_usage_headers(None, usage)

    # Verify result is a dict with usage headers
    assert isinstance(result_headers, dict), "Result must be a dict"
    assert "x-usage-prompt-tokens" in result_headers
    assert "x-usage-completion-tokens" in result_headers
    assert "x-usage-total-tokens" in result_headers


@given(
    existing_header_key=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=20,
    ),
    existing_header_value=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=50,
    ),
)
@property_test_settings()
def test_property_7_no_usage_returns_empty_headers(
    existing_header_key: str, existing_header_value: str
) -> None:
    """
    **Feature: gemini-oauth-streaming-fix, Property 7: Usage format translation**
    **Validates: Requirements 4.3**

    When usage is None, the _apply_usage_headers function SHALL return
    the original headers without adding usage headers.
    """
    existing_headers = {existing_header_key: existing_header_value}

    # Apply with None usage
    result_headers = _apply_usage_headers(existing_headers.copy(), None)

    # Verify existing headers are preserved
    assert (
        result_headers == existing_headers
    ), f"Headers should be unchanged when usage is None: {result_headers}"

    # Verify no usage headers were added
    assert "x-usage-prompt-tokens" not in result_headers
    assert "x-usage-completion-tokens" not in result_headers
    assert "x-usage-total-tokens" not in result_headers
