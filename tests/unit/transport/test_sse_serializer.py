"""
Tests for SSESerializer.

This module contains comprehensive tests for the SSE serializer covering
all edge cases including error chunks, cancellation, empty completions,
and tool-call sanitization.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.domain.streaming.stop_chunk_with_usage import StopChunkWithUsage
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.domain.usage_summary import UsageSummary
from src.core.transport.streaming.sse_serializer import SSESerializer


class TestSSESerializerErrorChunks:
    """Test error chunk serialization."""

    def test_error_chunk_with_metadata(self) -> None:
        """Error chunks with metadata should serialize to proper error payload."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {
                    "type": "AuthenticationError",
                    "message": "No auth credentials found",
                    "code": "unknown",
                    "retryable": False,
                    "status_code": 401,
                },
                "id": "chatcmpl-error-123",
                "model": "test-model",
                "created": 1234567890,
            },
            is_done=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should have proper SSE format
        assert result_str.startswith("data: ")
        assert "data: [DONE]" in result_str

        # Extract JSON payload
        lines = result_str.strip().split("\n\n")
        json_line = lines[0][6:]  # Remove "data: " prefix
        payload = json.loads(json_line)

        # Verify error payload structure
        assert "choices" in payload
        assert payload["choices"][0]["finish_reason"] == "error"
        assert "error" in payload
        assert payload["error"]["type"] == "AuthenticationError"
        assert payload["id"] == "chatcmpl-error-123"
        assert payload["model"] == "test-model"
        assert payload["created"] == 1234567890

    def test_error_chunk_with_content_dict_error(self) -> None:
        """Error chunks with error in content dict should serialize correctly."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={
                "id": "chatcmpl-error-content",
                "error": {"message": "Backend error", "type": "api_error"},
            },
            metadata={},
            is_done=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        assert result_str.startswith("data: ")
        assert "data: [DONE]" in result_str

        # Extract JSON payload
        lines = result_str.strip().split("\n\n")
        json_line = lines[0][6:]
        payload = json.loads(json_line)

        assert "error" in payload
        assert payload["error"]["message"] == "Backend error"

    def test_error_chunk_never_serializes_to_done_only(self) -> None:
        """Error chunks should never serialize to just [DONE], even with empty content."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": {"message": "Error occurred", "type": "error"},
            },
            is_done=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should NOT be just [DONE]
        assert result_str != "data: [DONE]\n\n"
        # Should contain error information
        assert "error" in result_str
        assert "Error occurred" in result_str

    def test_error_chunk_with_string_metadata(self) -> None:
        """String error metadata should serialize into error message."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "error": "payload_too_large",
            },
            is_done=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")
        lines = result_str.strip().split("\n\n")
        json_line = lines[0][6:]
        payload = json.loads(json_line)

        assert payload["choices"][0]["finish_reason"] == "error"
        assert payload["error"]["message"] == "payload_too_large"


class TestSSESerializerCancellationChunks:
    """Test cancellation chunk serialization."""

    def test_cancellation_chunk_with_content(self) -> None:
        """Cancellation chunks should serialize with cancellation message."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Request cancelled by user",
            metadata={
                "id": "chatcmpl-cancel-123",
                "model": "test-model",
                "created": 1234567890,
            },
            is_done=True,
            is_cancellation=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        assert result_str.startswith("data: ")
        assert "data: [DONE]" in result_str

        # Extract JSON payload
        lines = result_str.strip().split("\n\n")
        json_line = lines[0][6:]
        payload = json.loads(json_line)

        # Cancellation chunks should be OpenAI-shaped
        assert "choices" in payload
        assert len(payload["choices"]) > 0
        assert payload["choices"][0]["finish_reason"] == "cancelled"
        assert payload["choices"][0]["delta"]["content"] == "Request cancelled by user"
        assert payload["id"] == "chatcmpl-cancel-123"

    def test_cancellation_chunk_without_content(self) -> None:
        """Cancellation chunks without content should still serialize."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={},
            is_done=True,
            is_cancellation=True,
        )

        result = serializer.serialize(chunk)
        # Should serialize to [DONE] if no content
        assert result == b"data: [DONE]\n\n"


class TestSSESerializerEmptyCompletions:
    """Test empty completion payload handling."""

    def test_empty_completion_payload_serializes_to_done(self) -> None:
        """Empty completion payloads should serialize to just [DONE]."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={"choices": [{"delta": {}}]},
            metadata={},
            is_done=True,
        )

        result = serializer.serialize(chunk)
        assert result == b"data: [DONE]\n\n"

    def test_completion_with_usage_not_empty(self) -> None:
        """Completion payloads with usage should not be treated as empty."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={"choices": [{"delta": {}}], "usage": {"total_tokens": 10}},
            metadata={},
            is_done=True,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should not be just [DONE]
        assert result_str != "data: [DONE]\n\n"
        assert "usage" in result_str


class TestSSESerializerToolCallSanitization:
    """Test tool-call sanitization."""

    def test_tool_calls_sanitize_internal_markers(self) -> None:
        """Tool calls should have internal markers removed."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "test", "arguments": "{}"},
                        "_internal_marker": "should be removed",
                        "extra_content": {"secret": "data"},
                    }
                ],
            },
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should contain tool_calls
        assert "tool_calls" in result_str
        # Should NOT contain internal markers
        assert "_internal_marker" not in result_str
        assert "extra_content" not in result_str
        # Should contain public fields
        assert "call_123" in result_str
        assert "test" in result_str

    def test_virtual_tool_calls_removed(self) -> None:
        """Virtual tool calls should be removed entirely."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "test", "arguments": "{}"},
                    }
                ],
                "_virtual_tool_calls": True,
            },
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Virtual tool calls should not appear in output
        assert "tool_calls" not in result_str or '"tool_calls": []' in result_str

    def test_tool_calls_in_content_dict_sanitized(self) -> None:
        """Tool calls in content dict should also be sanitized."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": "call_456",
                                    "type": "function",
                                    "function": {"name": "test2", "arguments": "{}"},
                                    "extra_content": {"secret": "data"},
                                }
                            ]
                        }
                    }
                ]
            },
            metadata={},
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should contain tool_calls
        assert "tool_calls" in result_str
        # Should NOT contain extra_content
        assert "extra_content" not in result_str
        # Should contain public fields
        assert "call_456" in result_str


class TestSSESerializerStopChunkWithUsage:
    """Test StopChunkWithUsage handling."""

    def test_stop_chunk_with_usage_serializes_correctly(self) -> None:
        """StopChunkWithUsage should serialize with usage at top level."""
        serializer = SSESerializer()
        chunk_data: dict[str, Any] = {
            "id": "chatcmpl-test123",
            "choices": [{"delta": {"content": "4"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 1,
                "total_tokens": 16,
            },
        }
        stop_chunk = StopChunkWithUsage(chunk_data)

        chunk = StreamingContent(
            content=stop_chunk,
            metadata={"finish_reason": "stop"},
            is_done=True,
            usage=UsageSummary.from_dict(chunk_data["usage"]),
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        # Should have data: prefix and end with [DONE]
        assert result_str.startswith("data: ")
        assert result_str.endswith("data: [DONE]\n\n")

        # Extract JSON payload
        lines = result_str.strip().split("\n\n")
        json_line = lines[0][6:]
        payload = json.loads(json_line)

        # Verify usage is at top level
        assert "usage" in payload
        assert payload["usage"]["total_tokens"] == 16
        assert payload["id"] == "chatcmpl-test123"

    def test_stop_chunk_with_usage_infers_finish_reason_for_tool_calls(self) -> None:
        """Regression: usage-bearing OpenAI chunks must not end with finish_reason=null.

        Some providers send a terminal usage chunk but omit finish_reason. Many
        OpenAI-compatible clients use finish_reason to dispatch tool calls.
        """
        serializer = SSESerializer()
        chunk_data: dict[str, Any] = {
            "id": "chatcmpl-test-toolcalls",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "type": "function",
                                "function": {"name": "bash", "arguments": "{}"},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        chunk = StreamingContent(
            content=StopChunkWithUsage(chunk_data),
            metadata={"provider": "openai"},
            is_done=True,
            usage=UsageSummary.from_dict(chunk_data["usage"]),
        )

        result = serializer.serialize(chunk).decode("utf-8")
        json_line = result.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)
        assert payload["choices"][0]["finish_reason"] == "tool_calls"


class TestSSESerializerNormalChunks:
    """Test normal (non-done) chunk serialization."""

    def test_normal_chunk_with_text_content(self) -> None:
        """Normal chunks with text content should serialize correctly."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Hello world",
            metadata={"provider": "openai", "role": "assistant"},
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        assert result_str.startswith("data: ")
        assert result_str.endswith("\n\n")
        assert "[DONE]" not in result_str

        # Extract JSON
        json_line = result_str.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)

        # OpenAI-compatible envelope fields
        assert payload["object"] == "chat.completion.chunk"
        assert payload["choices"][0]["index"] == 0
        assert payload["choices"][0]["finish_reason"] is None

        assert payload["choices"][0]["delta"]["content"] == "Hello world"
        assert payload["choices"][0]["delta"]["role"] == "assistant"

    def test_normal_chunk_with_reasoning_content(self) -> None:
        """Normal chunks with reasoning content should include it."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Answer",
            metadata={
                "provider": "anthropic",
                "reasoning_content": "Let me think...",
            },
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        assert "reasoning_content" in result_str
        assert "Let me think..." in result_str

    def test_suppress_reasoning_fields_omits_reasoning_content(self) -> None:
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Answer",
            metadata={
                "provider": "anthropic",
                "reasoning_content": "Let me think...",
                "_suppress_reasoning_fields": True,
            },
            is_done=False,
        )

        result_str = serializer.serialize(chunk).decode("utf-8")

        assert "reasoning_content" not in result_str
        assert "Let me think..." not in result_str

    def test_suppress_reasoning_fields_coerces_reasoning_delta_to_content(self) -> None:
        serializer = SSESerializer()
        openai_chunk: dict[str, Any] = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "reasoning_content": "I'll check...",
                        "thinking": "I'll check...",
                        "thought": "I'll check...",
                        "content": "",
                    },
                    "finish_reason": None,
                }
            ],
        }
        chunk = StreamingContent(
            content=openai_chunk,
            metadata={"_suppress_reasoning_fields": True},
            is_done=False,
        )

        result_str = serializer.serialize(chunk).decode("utf-8")
        json_line = result_str.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)
        delta = payload["choices"][0]["delta"]

        assert delta["content"] == "I'll check..."
        assert "reasoning_content" not in delta
        assert "thinking" not in delta
        assert "thought" not in delta

    def test_suppress_reasoning_fields_keep_reasoning_content_preserves_canonical_field(
        self,
    ) -> None:
        """opencode-compatible mode keeps reasoning_content without duplicating in content."""
        serializer = SSESerializer()
        openai_chunk: dict[str, Any] = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "reasoning_content": "I'll check...",
                        "thinking": "I'll check...",
                        "thought": "I'll check...",
                        "content": "",
                    },
                    "finish_reason": None,
                }
            ],
        }
        chunk = StreamingContent(
            content=openai_chunk,
            metadata={
                "_suppress_reasoning_fields": True,
                "_keep_reasoning_content": True,
            },
            is_done=False,
        )

        result_str = serializer.serialize(chunk).decode("utf-8")
        json_line = result_str.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)
        delta = payload["choices"][0]["delta"]

        assert delta["content"] == ""
        assert delta["reasoning_content"] == "I'll check..."
        assert "thinking" not in delta
        assert "thought" not in delta

    def test_normal_chunk_with_finish_reason(self) -> None:
        """Normal chunks with finish_reason should include it."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Final",
            metadata={"finish_reason": "stop"},
            is_done=False,
        )

        result = serializer.serialize(chunk)
        result_str = result.decode("utf-8")

        json_line = result_str.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)

        assert payload["choices"][0]["finish_reason"] == "stop"
