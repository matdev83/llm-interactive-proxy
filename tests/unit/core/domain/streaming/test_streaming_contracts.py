"""
Tests for typed streaming contracts and bridge methods.

These tests verify that Pydantic v2 typed contracts work correctly and that
the bridge methods on StreamingContent can convert between legacy dict-based
and typed contract representations while preserving all behavior.
"""

from __future__ import annotations

import base64
import json

import pytest
from pydantic import ValidationError
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.domain.streaming.contracts import (
    StreamingChunk,
    StreamingErrorInfo,
    StreamingMetadata,
    StreamingPayload,
    StreamingUsage,
)
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming_contracts import StopChunkWithUsage


class TestTypedContractCreation:
    """Test that typed contract models can be created and validated."""

    def test_streaming_error_info_creation(self):
        """StreamingErrorInfo should be creatable with required fields."""
        error = StreamingErrorInfo(type="error", message="Test error")
        assert error.type == "error"
        assert error.message == "Test error"
        assert error.code is None
        assert error.retryable is None

    def test_streaming_error_info_with_optional_fields(self):
        """StreamingErrorInfo should accept optional fields."""
        error = StreamingErrorInfo(
            type="timeout", message="Request timed out", code="TIMEOUT", retryable=True
        )
        assert error.type == "timeout"
        assert error.message == "Request timed out"
        assert error.code == "TIMEOUT"
        assert error.retryable is True

    def test_streaming_error_info_with_status_code(self):
        """StreamingErrorInfo should accept status_code field."""
        error = StreamingErrorInfo(
            type="error",
            message="Test error",
            code="ERR001",
            status_code=503,
        )
        assert error.type == "error"
        assert error.message == "Test error"
        assert error.code == "ERR001"
        assert error.status_code == 503

    def test_streaming_error_info_rejects_extra_fields(self):
        """StreamingErrorInfo should reject extra fields."""
        with pytest.raises(ValidationError):
            StreamingErrorInfo(type="error", message="test", extra_field="not allowed")

    def test_streaming_usage_creation(self):
        """StreamingUsage should be creatable with token counts."""
        usage = StreamingUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 5
        assert usage.total_tokens == 15

    def test_streaming_usage_all_optional(self):
        """StreamingUsage should allow all fields to be None."""
        usage = StreamingUsage()
        assert usage.prompt_tokens is None
        assert usage.completion_tokens is None
        assert usage.total_tokens is None

    def test_streaming_metadata_creation(self):
        """StreamingMetadata should be creatable with various fields."""
        metadata = StreamingMetadata(
            provider="openai",
            stream_id="stream-123",
            finish_reason="stop",
            role="assistant",
        )
        assert metadata.provider == "openai"
        assert metadata.stream_id == "stream-123"
        assert metadata.finish_reason == "stop"
        assert metadata.role == "assistant"

    def test_streaming_metadata_with_tool_calls(self):
        """StreamingMetadata should accept ToolCall list."""
        tool_call = ToolCall(
            id="call-123",
            type="function",
            function=FunctionCall(name="test_function", arguments='{"x": 1}'),
        )
        metadata = StreamingMetadata(tool_calls=[tool_call])
        assert len(metadata.tool_calls) == 1
        assert metadata.tool_calls[0].id == "call-123"

    def test_streaming_metadata_with_error(self):
        """StreamingMetadata should accept StreamingErrorInfo."""
        error = StreamingErrorInfo(type="error", message="Test")
        metadata = StreamingMetadata(error=error)
        assert metadata.error is not None
        assert metadata.error.message == "Test"

    def test_streaming_metadata_with_usage(self):
        """StreamingMetadata should accept StreamingUsage."""
        usage = StreamingUsage(total_tokens=100)
        metadata = StreamingMetadata(usage=usage)
        assert metadata.usage is not None
        assert metadata.usage.total_tokens == 100

    def test_streaming_payload_text_kind(self):
        """StreamingPayload should support text kind."""
        payload = StreamingPayload(kind="text", text="Hello world")
        assert payload.kind == "text"
        assert payload.text == "Hello world"

    def test_streaming_payload_opaque_json_kind(self):
        """StreamingPayload should support opaque_json kind."""
        json_str = json.dumps({"key": "value"})
        payload = StreamingPayload(kind="opaque_json", opaque_json=json_str)
        assert payload.kind == "opaque_json"
        assert payload.opaque_json == json_str

    def test_streaming_payload_binary_kind(self):
        """StreamingPayload should support binary kind."""
        binary_data = b"binary content"
        binary_b64 = base64.b64encode(binary_data).decode("utf-8")
        payload = StreamingPayload(kind="binary", binary_b64=binary_b64)
        assert payload.kind == "binary"
        assert payload.binary_b64 == binary_b64

    def test_streaming_payload_empty_kind(self):
        """StreamingPayload should support empty kind."""
        payload = StreamingPayload(kind="empty")
        assert payload.kind == "empty"
        assert payload.text is None

    def test_streaming_chunk_creation(self):
        """StreamingChunk should combine payload and metadata."""
        payload = StreamingPayload(kind="text", text="Hello")
        metadata = StreamingMetadata(provider="openai")
        chunk = StreamingChunk(
            payload=payload, metadata=metadata, is_done=False, is_empty=False
        )
        assert chunk.payload.kind == "text"
        assert chunk.metadata.provider == "openai"
        assert chunk.is_done is False
        assert chunk.is_empty is False


class TestStreamingContentToTypedChunk:
    """Test StreamingContent.to_typed_chunk() conversion."""

    def test_text_content_to_typed_chunk(self):
        """Text content should convert to text payload kind."""
        sc = StreamingContent(content="Hello world", metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        assert chunk.payload.kind == "text"
        assert chunk.payload.text == "Hello world"

    def test_dict_content_to_typed_chunk(self):
        """Dict content should convert to opaque_json_dict payload kind."""
        content_dict = {"key": "value", "nested": {"inner": 123}}
        sc = StreamingContent(content=content_dict, metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        assert chunk.payload.kind == "opaque_json_dict"
        # Should be dict directly
        assert chunk.payload.opaque_json_dict == content_dict

    def test_bytes_content_to_typed_chunk(self):
        """Bytes content should convert to binary payload kind."""
        binary_data = b"binary content"
        sc = StreamingContent(content=binary_data, metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        assert chunk.payload.kind == "binary"
        decoded = base64.b64decode(chunk.payload.binary_b64)
        assert decoded == binary_data

    def test_empty_content_to_typed_chunk(self):
        """Empty content should convert to empty payload kind."""
        sc = StreamingContent(content="", metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        assert chunk.payload.kind == "empty"

    def test_metadata_conversion(self):
        """Metadata dict should convert to StreamingMetadata."""
        sc = StreamingContent(
            content="test",
            metadata={"provider": "openai", "stream_id": "stream-123"},
            is_done=False,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.provider == "openai"
        assert chunk.metadata.stream_id == "stream-123"

    def test_metadata_with_tool_calls_conversion(self):
        """Metadata with tool_calls should convert to ToolCall list."""
        tool_call_dict = {
            "id": "call-123",
            "type": "function",
            "function": {"name": "test_function", "arguments": '{"x": 1}'},
        }
        sc = StreamingContent(
            content="test",
            metadata={"tool_calls": [tool_call_dict]},
            is_done=False,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.tool_calls is not None
        assert len(chunk.metadata.tool_calls) == 1
        assert chunk.metadata.tool_calls[0].id == "call-123"
        assert chunk.metadata.tool_calls[0].function.name == "test_function"

    def test_metadata_with_error_conversion(self):
        """Metadata with error should convert to StreamingErrorInfo."""
        error_dict = {"type": "error", "message": "Test error", "code": "ERR001"}
        sc = StreamingContent(
            content="test",
            metadata={"error": error_dict},
            is_done=False,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.error is not None
        assert chunk.metadata.error.type == "error"
        assert chunk.metadata.error.message == "Test error"
        assert chunk.metadata.error.code == "ERR001"

    def test_metadata_with_error_status_code_conversion(self):
        """Metadata with error including status_code should convert correctly."""
        error_dict = {
            "type": "error",
            "message": "Test error",
            "code": "ERR001",
            "status_code": 503,
        }
        sc = StreamingContent(
            content="test",
            metadata={"error": error_dict},
            is_done=False,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.error is not None
        assert chunk.metadata.error.type == "error"
        assert chunk.metadata.error.message == "Test error"
        assert chunk.metadata.error.code == "ERR001"
        assert chunk.metadata.error.status_code == 503

    def test_metadata_with_error_int_code_conversion(self):
        """Metadata with int code should coerce to string."""
        error_dict = {"type": "error", "message": "Test error", "code": 400}
        sc = StreamingContent(
            content="test",
            metadata={"error": error_dict},
            is_done=False,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.error is not None
        assert chunk.metadata.error.code == "400"

    def test_usage_dict_conversion(self):
        """Usage dict should convert to StreamingUsage."""
        usage_dict = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        sc = StreamingContent(
            content="test", metadata={}, is_done=False, usage=usage_dict
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.usage is not None
        assert chunk.metadata.usage.prompt_tokens == 10
        assert chunk.metadata.usage.completion_tokens == 5
        assert chunk.metadata.usage.total_tokens == 15

    def test_usage_dict_accepts_anthropic_input_output_token_keys(self) -> None:
        """Messages API streams often emit input_tokens/output_tokens (+ cache fields)."""
        usage_dict = {
            "input_tokens": 35,
            "output_tokens": 69,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 15675,
        }
        sc = StreamingContent(
            content="test", metadata={}, is_done=False, usage=usage_dict
        )
        chunk = sc.to_typed_chunk()
        assert chunk.metadata.usage is not None
        assert chunk.metadata.usage.prompt_tokens == 35
        assert chunk.metadata.usage.completion_tokens == 69
        assert chunk.metadata.usage.cache_read_input_tokens == 15675

    def test_flags_preserved(self):
        """is_done, is_empty, is_cancellation flags should be preserved."""
        sc = StreamingContent(
            content="test",
            metadata={},
            is_done=True,
            is_empty=False,
            is_cancellation=True,
        )
        chunk = sc.to_typed_chunk()
        assert chunk.is_done is True
        assert chunk.is_empty is False
        assert chunk.is_cancellation is True

    def test_stop_chunk_with_usage_preserved(self):
        """StopChunkWithUsage should be preserved as opaque_json_dict in content."""
        stop_chunk_data = {
            "id": "chatcmpl-test",
            "choices": [{"delta": {"content": "final"}}],
            "usage": {"total_tokens": 10},
        }
        stop_chunk = StopChunkWithUsage(stop_chunk_data)
        sc = StreamingContent(
            content=stop_chunk,
            metadata={},
            is_done=True,
            usage=stop_chunk_data["usage"],
        )
        chunk = sc.to_typed_chunk()
        # StopChunkWithUsage should be converted to opaque_json_dict
        assert chunk.payload.kind == "opaque_json_dict"
        assert chunk.payload.opaque_json_dict["id"] == "chatcmpl-test"


class TestStreamingContentFromTypedChunk:
    """Test StreamingContent.from_typed_chunk() conversion."""

    def test_text_payload_to_streaming_content(self):
        """Text payload should convert back to StreamingContent."""
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="text", text="Hello world"),
            metadata=StreamingMetadata(),
            is_done=False,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert sc.content == "Hello world"
        assert sc.is_done is False
        assert sc.is_empty is False

    def test_opaque_json_payload_to_streaming_content(self):
        """Opaque JSON payload should convert back to dict."""
        content_dict = {"key": "value"}
        json_str = json.dumps(content_dict)
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="opaque_json", opaque_json=json_str),
            metadata=StreamingMetadata(),
            is_done=False,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert isinstance(sc.content, dict)
        assert sc.content == content_dict

    def test_binary_payload_to_streaming_content(self):
        """Binary payload should convert back to bytes."""
        binary_data = b"binary content"
        binary_b64 = base64.b64encode(binary_data).decode("utf-8")
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="binary", binary_b64=binary_b64),
            metadata=StreamingMetadata(),
            is_done=False,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert isinstance(sc.content, bytes)
        assert sc.content == binary_data

    def test_empty_payload_to_streaming_content(self):
        """Empty payload should convert to empty string."""
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="empty"),
            metadata=StreamingMetadata(),
            is_done=False,
            is_empty=True,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert sc.content == ""
        assert sc.is_empty is True

    def test_metadata_conversion_back(self):
        """StreamingMetadata should convert back to dict."""
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="text", text="test"),
            metadata=StreamingMetadata(
                provider="openai", stream_id="stream-123", finish_reason="stop"
            ),
            is_done=True,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert sc.metadata["provider"] == "openai"
        assert sc.metadata["stream_id"] == "stream-123"
        assert sc.metadata["finish_reason"] == "stop"

    def test_tool_calls_conversion_back(self):
        """ToolCall list should convert back to dict list."""
        tool_call = ToolCall(
            id="call-123",
            type="function",
            function=FunctionCall(name="test_function", arguments='{"x": 1}'),
        )
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="text", text="test"),
            metadata=StreamingMetadata(tool_calls=[tool_call]),
            is_done=False,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert "tool_calls" in sc.metadata
        assert len(sc.metadata["tool_calls"]) == 1
        tool_call_dict = sc.metadata["tool_calls"][0]
        assert tool_call_dict["id"] == "call-123"
        assert tool_call_dict["function"]["name"] == "test_function"

    def test_error_info_conversion_back(self):
        """StreamingErrorInfo should convert back to error dict."""
        error = StreamingErrorInfo(
            type="error", message="Test error", code="ERR001", retryable=True
        )
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="empty"),
            metadata=StreamingMetadata(error=error),
            is_done=True,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert "error" in sc.metadata
        assert sc.metadata["error"]["type"] == "error"
        assert sc.metadata["error"]["message"] == "Test error"
        assert sc.metadata["error"]["code"] == "ERR001"
        assert sc.metadata["error"]["retryable"] is True

    def test_error_info_with_status_code_conversion_back(self):
        """StreamingErrorInfo with status_code should convert back correctly."""
        error = StreamingErrorInfo(
            type="error",
            message="Test error",
            code="ERR001",
            retryable=True,
            status_code=503,
        )
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="empty"),
            metadata=StreamingMetadata(error=error),
            is_done=True,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert "error" in sc.metadata
        assert sc.metadata["error"]["type"] == "error"
        assert sc.metadata["error"]["message"] == "Test error"
        assert sc.metadata["error"]["code"] == "ERR001"
        assert sc.metadata["error"]["retryable"] is True
        assert sc.metadata["error"]["status_code"] == 503

    def test_usage_conversion_back(self):
        """StreamingUsage should convert back to usage dict."""
        usage = StreamingUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        chunk = StreamingChunk(
            payload=StreamingPayload(kind="text", text="test"),
            metadata=StreamingMetadata(usage=usage),
            is_done=False,
            is_empty=False,
        )
        sc = StreamingContent.from_typed_chunk(chunk)
        assert sc.usage is not None
        assert sc.usage["prompt_tokens"] == 10
        assert sc.usage["completion_tokens"] == 5
        assert sc.usage["total_tokens"] == 15


class TestRoundTripCompatibility:
    """Test round-trip conversion preserves all data."""

    def test_text_content_round_trip(self):
        """Text content should round-trip correctly."""
        original = StreamingContent(
            content="Hello world",
            metadata={"provider": "openai"},
            is_done=False,
            is_empty=False,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.content == original.content
        assert restored.metadata == original.metadata
        assert restored.is_done == original.is_done
        assert restored.is_empty == original.is_empty

    def test_dict_content_round_trip(self):
        """Dict content should round-trip correctly."""
        content_dict = {"key": "value", "nested": {"inner": 123}}
        original = StreamingContent(
            content=content_dict,
            metadata={"provider": "openai", "stream_id": "stream-123"},
            is_done=True,
            is_empty=False,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.content == original.content
        assert restored.metadata == original.metadata
        assert restored.is_done == original.is_done

    def test_tool_calls_round_trip(self):
        """Tool calls should round-trip correctly."""
        tool_call_dict = {
            "id": "call-123",
            "type": "function",
            "function": {"name": "test_function", "arguments": '{"x": 1}'},
        }
        original = StreamingContent(
            content="test",
            metadata={"tool_calls": [tool_call_dict]},
            is_done=False,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert len(restored.metadata["tool_calls"]) == 1
        assert restored.metadata["tool_calls"][0]["id"] == "call-123"

    def test_error_info_round_trip(self):
        """Error info should round-trip correctly."""
        error_dict = {"type": "error", "message": "Test", "code": "ERR001"}
        original = StreamingContent(
            content="test",
            metadata={"error": error_dict},
            is_done=True,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.metadata["error"] == error_dict

    def test_error_info_with_status_code_round_trip(self):
        """Error info with status_code should round-trip correctly."""
        error_dict = {
            "type": "error",
            "message": "Test",
            "code": "ERR001",
            "status_code": 503,
        }
        original = StreamingContent(
            content="test",
            metadata={"error": error_dict},
            is_done=True,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        # status_code should be preserved in round-trip
        assert restored.metadata["error"]["type"] == "error"
        assert restored.metadata["error"]["message"] == "Test"
        assert restored.metadata["error"]["code"] == "ERR001"
        assert restored.metadata["error"]["status_code"] == 503

    def test_usage_round_trip(self):
        """Usage should round-trip correctly."""
        usage_dict = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        original = StreamingContent(
            content="test", metadata={}, is_done=False, usage=usage_dict
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.usage == usage_dict

    def test_all_flags_round_trip(self):
        """All flags should round-trip correctly."""
        original = StreamingContent(
            content="test",
            metadata={},
            is_done=True,
            is_empty=False,
            is_cancellation=True,
        )
        chunk = original.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.is_done == original.is_done
        assert restored.is_empty == original.is_empty
        assert restored.is_cancellation == original.is_cancellation


class TestCompatibilityWithExistingCode:
    """Test that bridge methods don't break existing functionality."""

    def test_to_bytes_still_works(self):
        """to_bytes() should still work after conversion."""
        sc = StreamingContent(content="test", metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        # Should not raise exception
        result = restored.to_bytes()
        assert isinstance(result, bytes)

    def test_whitespace_only_content_preserved(self):
        """Whitespace-only content should be preserved (non-empty)."""
        sc = StreamingContent(content="   ", metadata={}, is_done=False)
        chunk = sc.to_typed_chunk()
        restored = StreamingContent.from_typed_chunk(chunk)
        assert restored.content == "   "
        assert restored.is_empty is False  # Whitespace is non-empty
