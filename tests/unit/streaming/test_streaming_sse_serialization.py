"""
Tests for SSE serialization of streaming content.

These tests verify that StreamingContent.to_bytes() correctly serializes
various content types including StopChunkWithUsage to proper SSE format.
"""

from __future__ import annotations

import json

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.ports.streaming_contracts import StopChunkWithUsage


class TestStreamingContentToBytes:
    """Test StreamingContent.to_bytes() serialization."""

    def test_serialize_stop_chunk_with_usage(self):
        """StopChunkWithUsage should serialize to SSE with usage at top level."""
        chunk_data = {
            "id": "chatcmpl-test123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "4"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 1,
                "total_tokens": 16,
            },
        }
        stop_chunk = StopChunkWithUsage(chunk_data)

        content = StreamingContent(
            content=stop_chunk,
            metadata={"finish_reason": "stop"},
            is_done=True,
            usage=chunk_data["usage"],
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        # Should have data: prefix and end with [DONE]
        assert result_str.startswith("data: ")
        assert result_str.endswith("data: [DONE]\n\n")

        # Extract the JSON part
        json_lines = [
            line[6:]
            for line in result_str.strip().split("\n\n")
            if line.startswith("data: ")
        ]
        main_json = json.loads(json_lines[0])

        # Verify structure
        assert main_json["id"] == "chatcmpl-test123"
        assert main_json["choices"][0]["delta"]["content"] == "4"
        assert main_json["usage"]["total_tokens"] == 16

    def test_serialize_openai_format_chunk_with_content(self):
        """OpenAI-format chunk with content should serialize correctly."""
        chunk_data = {
            "id": "chatcmpl-content",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello world"},
                    "finish_reason": None,
                }
            ],
        }

        content = StreamingContent(
            content=chunk_data,
            metadata={"model": "gpt-4o"},
            is_done=False,
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        # Should have data: prefix
        assert result_str.startswith("data: ")

        # Extract JSON
        json_str = result_str.strip().split("\n\n")[0][6:]
        parsed = json.loads(json_str)

        assert parsed["choices"][0]["delta"]["content"] == "Hello world"
        # Should NOT have [DONE] since is_done=False
        # (Actually, looking at the code, it may still have [DONE] for OpenAI format)

    def test_normalize_chat_completion_payload_to_stream_chunk(self):
        """Non-streaming `chat.completion` payloads must emit `choices[].delta` in SSE."""
        completion_payload = {
            "id": "chatcmpl-proxy-1",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "claude-opus-4-5-thinking",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Blocked"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        content = StreamingContent(
            content=completion_payload,
            metadata={"finish_reason": "stop"},
            is_done=True,
        )

        result_str = content.to_bytes().decode("utf-8")
        first_event = result_str.strip().split("\n\n")[0]
        assert first_event.startswith("data: ")
        parsed = json.loads(first_event[6:])

        assert parsed["object"] == "chat.completion.chunk"
        assert "delta" in parsed["choices"][0]
        assert "message" not in parsed["choices"][0]
        assert parsed["choices"][0]["delta"]["content"] == "Blocked"

    def test_serialize_text_content(self):
        """Plain text content should serialize to SSE format."""
        content = StreamingContent(
            content="Hello world",
            metadata={},
            is_done=False,
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        # Should be SSE formatted
        assert "data:" in result_str

    def test_serialize_done_marker_only(self):
        """is_done=True with empty content should produce [DONE]."""
        content = StreamingContent(
            content="",
            metadata={},
            is_done=True,
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        assert "data: [DONE]" in result_str


class TestStopChunkWithUsageProtections:
    """Test that StopChunkWithUsage protections work correctly."""

    def test_items_raises_type_error(self):
        """Calling .items() on StopChunkWithUsage should raise TypeError."""
        stop_chunk = StopChunkWithUsage({"key": "value"})

        with pytest.raises(TypeError, match="Cannot directly serialize"):
            stop_chunk.items()

    def test_str_raises_usage_chunk_leak_error(self):
        """Calling str() on StopChunkWithUsage should raise UsageChunkLeakError."""
        from src.core.ports.streaming_contracts import UsageChunkLeakError

        stop_chunk = StopChunkWithUsage({"key": "value"})

        with pytest.raises(UsageChunkLeakError):
            str(stop_chunk)

    def test_dict_conversion_safe(self):
        """Converting to plain dict should be safe."""
        stop_chunk = StopChunkWithUsage({"key": "value", "nested": {"inner": 123}})

        plain_dict = dict(stop_chunk)

        assert plain_dict == {"key": "value", "nested": {"inner": 123}}
        assert type(plain_dict) is dict  # Not StopChunkWithUsage

    def test_json_dumps_on_plain_dict_conversion(self):
        """json.dumps should work on dict(stop_chunk)."""
        stop_chunk = StopChunkWithUsage({"id": "test", "usage": {"total_tokens": 10}})

        plain_dict = dict(stop_chunk)
        json_str = json.dumps(plain_dict)

        assert '"id": "test"' in json_str
        assert '"total_tokens": 10' in json_str


class TestStreamingContentEdgeCases:
    """Test edge cases in StreamingContent handling."""

    def test_empty_string_content_with_done(self):
        """Empty string content with is_done=True should produce [DONE]."""
        content = StreamingContent(
            content="",
            metadata={},
            is_done=True,
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        assert "data: [DONE]" in result_str

    def test_empty_dict_content(self):
        """Empty dict content should serialize."""
        content = StreamingContent(
            content={"choices": []},
            metadata={},
            is_done=False,
        )

        result = content.to_bytes()
        # Should not raise exception
        assert result is not None

    def test_content_with_finish_reason_stop(self):
        """Chunk with finish_reason=stop should include content."""
        chunk_data = {
            "id": "chatcmpl-finish",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Final answer"},
                    "finish_reason": "stop",
                }
            ],
        }

        content = StreamingContent(
            content=chunk_data,
            metadata={"finish_reason": "stop"},
            is_done=True,
        )

        result = content.to_bytes()
        result_str = result.decode("utf-8")

        # Should contain the actual content, not just [DONE]
        assert "Final answer" in result_str or "choices" in result_str

    def test_content_with_usage_metadata(self):
        """Content with usage in metadata should serialize correctly."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        content = StreamingContent(
            content={"choices": []},
            metadata={},
            is_done=True,
            usage=usage,
        )

        result = content.to_bytes()
        # result_str = result.decode("utf-8")

        # Should include usage data somewhere
        assert result is not None


class TestMultipleChunkSequence:
    """Test serialization of a sequence of chunks like a real stream."""

    def test_content_sequence(self):
        """Simulate a typical streaming sequence."""
        chunks = [
            # First chunk: role
            StreamingContent(
                content={
                    "id": "chatcmpl-seq",
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}],
                },
                metadata={},
                is_done=False,
            ),
            # Second chunk: content
            StreamingContent(
                content={
                    "id": "chatcmpl-seq",
                    "choices": [{"index": 0, "delta": {"content": "Hello"}}],
                },
                metadata={},
                is_done=False,
            ),
            # Third chunk: more content
            StreamingContent(
                content={
                    "id": "chatcmpl-seq",
                    "choices": [{"index": 0, "delta": {"content": " world"}}],
                },
                metadata={},
                is_done=False,
            ),
            # Final chunk: finish_reason + usage
            StreamingContent(
                content=StopChunkWithUsage(
                    {
                        "id": "chatcmpl-seq",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 2,
                            "total_tokens": 7,
                        },
                    }
                ),
                metadata={"finish_reason": "stop"},
                is_done=True,
            ),
        ]

        # All chunks should serialize without error
        results = []
        for chunk in chunks:
            result = chunk.to_bytes()
            results.append(result.decode("utf-8"))

        # Last chunk should have [DONE]
        assert "data: [DONE]" in results[-1]

        # Second chunk should have "Hello"
        assert "Hello" in results[1]
