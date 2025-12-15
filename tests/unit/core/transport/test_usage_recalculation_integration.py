"""Integration tests for usage recalculation in response adapters."""

from __future__ import annotations

import json

from src.core.domain.responses import ResponseEnvelope
from src.core.transport.fastapi.response_adapters import to_fastapi_response


def test_usage_recalculated_when_content_differs():
    """Test that usage is recalculated when content size differs significantly from original."""
    # Simulate a response where content has been compressed
    # Original backend reported 500 completion tokens, but actual content is much smaller
    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Short response",  # ~3 tokens
                    },
                    "finish_reason": "stop",
                }
            ],
        },
        headers={"x-request-id": "req-123"},
        status_code=200,
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 500,  # Much higher than actual content
            "total_tokens": 600,
        },
        metadata={"allow_usage_recalculation": True},
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body

    assert response.headers["x-usage-prompt-tokens"] == str(
        body["usage"]["prompt_tokens"]
    )
    assert response.headers["x-usage-completion-tokens"] == str(
        body["usage"]["completion_tokens"]
    )
    assert response.headers["x-usage-total-tokens"] == str(
        body["usage"]["total_tokens"]
    )

    # Usage should be recalculated because difference is >5% and >10 tokens
    assert body["usage"]["prompt_tokens"] == 100  # Preserved
    assert body["usage"]["completion_tokens"] < 500  # Recalculated
    assert body["usage"]["completion_tokens"] < 10  # Should be close to actual (~3)
    assert (
        body["usage"]["total_tokens"]
        == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )


def test_usage_not_recalculated_when_close():
    """Test that usage is not recalculated when content matches expected size."""
    # Content size matches the reported usage (within 5% threshold)
    # Actual: ~125 tokens, Reported: 130 tokens = 3.8% difference (below 5% threshold)
    content_text = "A" * 1000  # ~125 tokens (tiktoken is efficient with repeated chars)

    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-456",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
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
        },
        headers={"x-request-id": "req-456"},
        status_code=200,
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 130,  # Close to actual (~125), within 5% threshold
            "total_tokens": 230,
        },
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body

    # Usage should NOT be recalculated because difference is small (<5% and <10 tokens)
    assert body["usage"]["prompt_tokens"] == 100
    assert body["usage"]["completion_tokens"] == 130  # Original value preserved
    assert body["usage"]["total_tokens"] == 230


def test_usage_recalculated_after_compression():
    """Test realistic scenario: pytest output compression."""
    # Simulate pytest output that was compressed from 5000 chars to 1500 chars
    # Actual token count for "X" * 1500 is ~188 tokens (tiktoken counts repeated chars efficiently)
    compressed_content = "X" * 1500  # ~188 tokens

    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-789",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": compressed_content,  # Compressed content
                    },
                    "finish_reason": "stop",
                }
            ],
        },
        headers={"x-request-id": "req-789"},
        status_code=200,
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 1250,  # Based on original uncompressed content
            "total_tokens": 1350,
        },
        metadata={"allow_usage_recalculation": True},
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body

    # Usage should be recalculated to match compressed content
    assert body["usage"]["prompt_tokens"] == 100  # Preserved
    assert body["usage"]["completion_tokens"] < 1250  # Recalculated
    assert 150 < body["usage"]["completion_tokens"] < 250  # Should be ~188
    assert (
        body["usage"]["total_tokens"]
        == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]
    )


def test_usage_preserved_for_non_chat_responses():
    """Test that usage is preserved for non-chat-completion responses."""
    # Response without choices (not a chat completion)
    envelope = ResponseEnvelope(
        content={
            "id": "test-999",
            "result": "some data",
        },
        headers={"x-request-id": "req-999"},
        status_code=200,
        usage={
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "total_tokens": 75,
        },
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body

    # Usage should be preserved as-is (no recalculation for non-chat responses)
    assert body["usage"]["prompt_tokens"] == 50
    assert body["usage"]["completion_tokens"] == 25
    assert body["usage"]["total_tokens"] == 75


def test_usage_recalculated_with_tool_calls():
    """Test that usage is recalculated even when response includes tool calls."""
    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-tool-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Small",  # ~1 token
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_function",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
        headers={"x-request-id": "req-tool-123"},
        status_code=200,
        usage={
            "prompt_tokens": 200,
            "completion_tokens": 300,  # Much higher than actual content
            "total_tokens": 500,
        },
        metadata={"allow_usage_recalculation": True},
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    assert "usage" in body

    # Usage should be recalculated based on content text
    assert body["usage"]["prompt_tokens"] == 200  # Preserved
    assert body["usage"]["completion_tokens"] < 300  # Recalculated
    assert body["usage"]["completion_tokens"] < 10  # Should be very small


def test_no_usage_in_envelope():
    """Test that responses without usage work correctly."""
    envelope = ResponseEnvelope(
        content={
            "id": "chatcmpl-no-usage",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Response without usage",
                    },
                    "finish_reason": "stop",
                }
            ],
        },
        headers={"x-request-id": "req-no-usage"},
        status_code=200,
        usage=None,  # No usage provided
    )

    # Act
    response = to_fastapi_response(envelope)

    # Assert
    body = json.loads(response.body)
    # Should not have usage field or should be None
    assert "usage" in body
    usage = body["usage"]
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert response.headers["x-usage-total-tokens"] == str(usage["total_tokens"])
