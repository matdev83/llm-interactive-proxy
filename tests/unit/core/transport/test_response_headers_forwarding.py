"""Test that provider-specific headers are properly forwarded to clients."""

from __future__ import annotations

import json

from src.core.domain.responses import ResponseEnvelope
from src.core.transport.fastapi.response_adapters import to_fastapi_response


def test_anthropic_headers_forwarded():
    """Test that Anthropic-specific headers are forwarded to the client."""
    # Arrange
    envelope = ResponseEnvelope(
        content={"message": "test"},
        headers={
            "anthropic-ratelimit-requests-limit": "1000",
            "anthropic-ratelimit-requests-remaining": "999",
            "anthropic-ratelimit-requests-reset": "2024-01-01T00:00:00Z",
            "anthropic-ratelimit-tokens-limit": "100000",
            "anthropic-ratelimit-tokens-remaining": "99500",
            "anthropic-ratelimit-tokens-reset": "2024-01-01T00:00:00Z",
            "x-request-id": "req-123",
        },
        status_code=200,
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    assert "anthropic-ratelimit-requests-limit" in response.headers
    assert response.headers["anthropic-ratelimit-requests-limit"] == "1000"
    assert "anthropic-ratelimit-tokens-remaining" in response.headers
    assert response.headers["anthropic-ratelimit-tokens-remaining"] == "99500"
    assert "x-request-id" in response.headers


def test_openai_headers_forwarded():
    """Test that OpenAI-specific headers are forwarded to the client."""
    # Arrange
    envelope = ResponseEnvelope(
        content={"message": "test"},
        headers={
            "openai-organization": "org-123",
            "openai-processing-ms": "1234",
            "openai-version": "2023-05-15",
            "x-request-id": "req-456",
        },
        status_code=200,
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    assert "openai-organization" in response.headers
    assert response.headers["openai-organization"] == "org-123"
    assert "openai-processing-ms" in response.headers
    assert response.headers["openai-processing-ms"] == "1234"
    assert "x-request-id" in response.headers


def test_custom_x_headers_forwarded():
    """Test that custom x- headers are forwarded to the client."""
    # Arrange
    envelope = ResponseEnvelope(
        content={"message": "test"},
        headers={
            "x-custom-header": "custom-value",
            "x-ratelimit-limit": "100",
            "x-ratelimit-remaining": "95",
        },
        status_code=200,
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    assert "x-custom-header" in response.headers
    assert response.headers["x-custom-header"] == "custom-value"
    assert "x-ratelimit-limit" in response.headers
    assert response.headers["x-ratelimit-remaining"] == "95"


def test_hop_by_hop_headers_filtered():
    """Test that hop-by-hop headers are filtered out."""
    # Arrange
    envelope = ResponseEnvelope(
        content={"message": "test"},
        headers={
            "x-request-id": "req-789",
            "content-encoding": "gzip",  # Should be filtered
            "transfer-encoding": "chunked",  # Should be filtered
            "connection": "keep-alive",  # Should be filtered
            "anthropic-ratelimit-requests-limit": "1000",  # Should be kept
        },
        status_code=200,
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    assert "x-request-id" in response.headers
    assert "anthropic-ratelimit-requests-limit" in response.headers
    assert "content-encoding" not in response.headers
    assert "transfer-encoding" not in response.headers
    assert "connection" not in response.headers


def test_usage_in_response_body():
    """Test that usage data is included in the response body."""
    # Arrange
    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        },
        headers={"x-request-id": "req-999"},
        status_code=200,
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body
    assert body["usage"]["prompt_tokens"] == 10  # Preserved
    # completion_tokens will be recalculated based on actual content ("Hello!" = ~2 tokens)
    assert body["usage"]["completion_tokens"] > 0
    assert (
        body["usage"]["total_tokens"]
        == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )


def test_cline_response_with_usage_and_headers():
    """Test that Cline responses include both usage data and headers."""
    # Arrange - Simulate a Cline backend response
    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-cline-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Response from Cline"},
                    "finish_reason": "stop",
                }
            ],
        },
        headers={
            "x-request-id": "cline-req-123",
            "x-ratelimit-limit": "1000",
            "x-ratelimit-remaining": "999",
        },
        status_code=200,
        usage={
            "prompt_tokens": 25,
            "completion_tokens": 15,
            "total_tokens": 40,
        },
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert - Headers are forwarded
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] == "cline-req-123"
    assert "x-ratelimit-limit" in response.headers
    assert response.headers["x-ratelimit-limit"] == "1000"

    # Assert - Usage is in body
    body = json.loads(response.body)
    assert "usage" in body
    assert body["usage"]["prompt_tokens"] == 25  # Preserved
    # completion_tokens will be recalculated based on actual content ("Response from Cline" = ~4 tokens)
    assert body["usage"]["completion_tokens"] > 0
    assert (
        body["usage"]["total_tokens"]
        == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )


def test_zenmux_headers_forwarded():
    """Test that ZenMux-specific headers are forwarded to the client."""
    # Arrange
    envelope = ResponseEnvelope(
        content={"message": "test"},
        headers={
            "zenmux-model-id": "gpt-4-turbo",
            "zenmux-region": "us-east-1",
            "zenmux-cost": "0.0025",
            "zenmux-processing-time": "123ms",
            "x-request-id": "req-zenmux-123",
        },
        status_code=200,
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    assert "zenmux-model-id" in response.headers
    assert response.headers["zenmux-model-id"] == "gpt-4-turbo"
    assert "zenmux-region" in response.headers
    assert response.headers["zenmux-region"] == "us-east-1"
    assert "zenmux-cost" in response.headers
    assert response.headers["zenmux-cost"] == "0.0025"
    assert "zenmux-processing-time" in response.headers
    assert "x-request-id" in response.headers
