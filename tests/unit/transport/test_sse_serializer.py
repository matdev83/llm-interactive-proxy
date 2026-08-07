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

    def test_error_chunk_with_content_dict_numeric_id(self) -> None:
        """Numeric provider error ids must stringify for strict SSE clients."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={
                "id": 884422,
                "error": {"message": "Backend error", "type": "api_error"},
            },
            metadata={},
            is_done=True,
        )

        result = serializer.serialize(chunk)
        lines = result.decode("utf-8").strip().split("\n\n")
        payload = json.loads(lines[0][6:])
        assert payload["id"] == "884422"

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

    def test_terminal_error_finish_reason_never_collapses_to_done_only(self) -> None:
        """Done chunks marked as error must serialize to structured error payload."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="",
            metadata={
                "finish_reason": "error",
                "model": "test-model",
            },
            is_done=True,
        )

        result_str = serializer.serialize(chunk).decode("utf-8")
        assert result_str != "data: [DONE]\n\n"
        assert "finish_reason" in result_str
        assert '"error"' in result_str


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

    def test_metadata_empty_arguments_does_not_clobber_delta_tool_calls(self) -> None:
        """Placeholder metadata.tool_calls must not replace richer delta.tool_calls."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={
                "id": "chatcmpl-proof",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "fc1",
                                    "type": "function",
                                    "function": {
                                        "name": "shell",
                                        "arguments": (
                                            '{"command":"git log -1","description":"d"}'
                                        ),
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            metadata={
                "id": "chatcmpl-proof",
                "created": 1,
                "model": "gpt-test",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "fc1",
                        "type": "function",
                        "function": {"name": "shell", "arguments": ""},
                    }
                ],
            },
            is_done=False,
        )

        result = serializer.serialize(chunk).decode("utf-8")
        assert "git log -1" in result

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
        """Usage-only stop chunks should serialize as the final include_usage chunk."""
        serializer = SSESerializer()
        chunk_data: dict[str, Any] = {
            "id": "chatcmpl-test123",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [],
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

        # Verify this is the standards-compliant final usage chunk
        assert "usage" in payload
        assert payload["usage"]["total_tokens"] == 16
        assert payload["id"] == "chatcmpl-test123"
        assert payload["choices"] == []

    def test_stop_chunk_with_usage_splits_terminal_tool_calls_delta(self) -> None:
        """Tool-call finals must end with a clean terminal marker.

        Strict OpenAI-compatible clients dispatch tool calls from the final
        ``finish_reason="tool_calls"`` frame. That marker must not also carry
        partial tool-call deltas or top-level usage.
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
        events = [part for part in result.strip().split("\n\n") if part]
        assert len(events) == 3

        delta_payload = json.loads(events[0][6:])
        terminal_payload = json.loads(events[1][6:])

        assert delta_payload["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
        assert delta_payload["choices"][0]["finish_reason"] is None
        assert "usage" not in delta_payload

        assert terminal_payload["choices"][0]["delta"] == {}
        assert terminal_payload["choices"][0]["finish_reason"] == "tool_calls"
        assert "usage" not in terminal_payload
        assert events[2] == "data: [DONE]"

    def test_done_openai_dict_strips_usage_from_clean_tool_calls_terminal(
        self,
    ) -> None:
        """Clean tool-call terminal frames must not carry usage."""
        serializer = SSESerializer()
        chunk_data: dict[str, Any] = {
            "id": "chatcmpl-test-toolcalls-clean",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        chunk = StreamingContent(
            content=chunk_data,
            metadata={"provider": "openai"},
            is_done=True,
            usage=UsageSummary.from_dict(chunk_data["usage"]),
        )

        result = serializer.serialize(chunk).decode("utf-8")
        events = [part for part in result.strip().split("\n\n") if part]

        assert len(events) == 2
        payload = json.loads(events[0][6:])
        assert payload["choices"][0]["delta"] == {}
        assert payload["choices"][0]["finish_reason"] == "tool_calls"
        assert "usage" not in payload
        assert events[1] == "data: [DONE]"

    def test_stop_chunk_with_usage_keeps_usage_on_single_sse_frame(self) -> None:
        """StopChunkWithUsage must emit one OpenAI JSON object with top-level usage."""
        serializer = SSESerializer()
        chunk_data: dict[str, Any] = {
            "id": "chatcmpl-test-split",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "4"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 1,
                "total_tokens": 16,
            },
        }
        chunk = StreamingContent(
            content=StopChunkWithUsage(chunk_data),
            metadata={"provider": "openai"},
            is_done=True,
            usage=UsageSummary.from_dict(chunk_data["usage"]),
        )

        result = serializer.serialize(chunk).decode("utf-8")
        events = [part for part in result.strip().split("\n\n") if part]

        assert len(events) == 2
        first_payload = json.loads(events[0][6:])

        assert first_payload["choices"][0]["delta"]["content"] == "4"
        assert first_payload["usage"]["total_tokens"] == 16
        assert events[1] == "data: [DONE]"


class TestSSESerializerNormalChunks:
    """Test normal (non-done) chunk serialization."""

    def test_coerce_reasoning_only_delta_to_content_for_strict_clients(self) -> None:
        serializer = SSESerializer()
        chunk = StreamingContent(
            content={
                "id": "chatcmpl-reasoning-only",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "reasoning_content": "Visible answer",
                            "content": "",
                        },
                        "finish_reason": None,
                    }
                ],
            },
            metadata={
                "_suppress_reasoning_fields": True,
                "_coerce_reasoning_into_content": True,
            },
        )

        result = serializer.serialize(chunk).decode("utf-8")
        payload = json.loads(result.strip().split("\n\n")[0][6:])
        delta = payload["choices"][0]["delta"]

        assert delta["content"] == "Visible answer"
        assert "reasoning_content" not in delta

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

    def test_openai_chunk_with_null_usage_does_not_infer_finish_reason(self) -> None:
        """Regression: `usage: null` must not cause finish_reason inference.

        Some providers include `"usage": null` on every streamed OpenAI chunk.
        Inferring finish_reason in that case can make clients stop reading after
        the first token.
        """

        serializer = SSESerializer()
        openai_chunk: dict[str, Any] = {
            "id": "chatcmpl-null-usage",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello"},
                    "finish_reason": None,
                }
            ],
            "usage": None,
        }
        chunk = StreamingContent(
            content=openai_chunk,
            metadata={"provider": "openai"},
            is_done=False,
        )

        result = serializer.serialize(chunk).decode("utf-8")
        json_line = result.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)
        assert payload["choices"][0]["finish_reason"] is None

        # Payload should be preserved; only finish_reason inference is under test.
        assert payload["choices"][0]["delta"]["content"] == "Hello"
        assert payload["choices"][0]["delta"]["role"] == "assistant"

    def test_normal_chunk_omits_non_terminal_usage(self) -> None:
        """Non-terminal legacy chat chunks must not emit non-null usage."""
        serializer = SSESerializer()
        chunk = StreamingContent(
            content="Hello",
            metadata={"provider": "openai"},
            is_done=False,
            usage=UsageSummary(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        result = serializer.serialize(chunk).decode("utf-8")
        payload = json.loads(result.strip().split("\n\n")[0][6:])

        assert "usage" not in payload

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

    def test_suppress_reasoning_fields_drop_mode_does_not_coerce(self) -> None:
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
                        "reasoning_content": "secret reasoning",
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
                "_coerce_reasoning_into_content": False,
            },
            is_done=False,
        )

        result_str = serializer.serialize(chunk).decode("utf-8")
        json_line = result_str.strip().split("\n\n")[0][6:]
        payload = json.loads(json_line)
        delta = payload["choices"][0]["delta"]

        assert delta["content"] == ""
        assert "reasoning_content" not in delta

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
