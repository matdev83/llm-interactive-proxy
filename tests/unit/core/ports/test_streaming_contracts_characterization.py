"""
Characterization tests for streaming_contracts.py public API.

These tests document the current public surface and behavioral invariants
that must be preserved during the refactoring. They serve as a regression
baseline to ensure backward compatibility.
"""

from __future__ import annotations

import json

import pytest
from src.core.ports.streaming_contracts import (
    BaseStreamNormalizer,
    IStreamAssembler,
    IStreamNormalizer,
    IStreamProcessor,
    SentinelManager,
    StopChunkWithUsage,
    StreamingContent,
    StreamingErrorMapper,
    UsageChunkLeakError,
    handle_streaming_error,
)


class TestPublicAPIImports:
    """Test that all public symbols are importable from streaming_contracts."""

    def test_streaming_content_importable(self):
        """StreamingContent should be importable."""
        assert StreamingContent is not None
        assert isinstance(StreamingContent, type)

    def test_stop_chunk_with_usage_importable(self):
        """StopChunkWithUsage should be importable."""
        assert StopChunkWithUsage is not None
        assert isinstance(StopChunkWithUsage, type)

    def test_usage_chunk_leak_error_importable(self):
        """UsageChunkLeakError should be importable."""
        assert UsageChunkLeakError is not None
        assert isinstance(UsageChunkLeakError, type)

    def test_istream_normalizer_importable(self):
        """IStreamNormalizer should be importable."""
        assert IStreamNormalizer is not None
        assert isinstance(IStreamNormalizer, type)

    def test_base_stream_normalizer_importable(self):
        """BaseStreamNormalizer should be importable."""
        assert BaseStreamNormalizer is not None
        assert isinstance(BaseStreamNormalizer, type)

    def test_istream_processor_importable(self):
        """IStreamProcessor should be importable."""
        assert IStreamProcessor is not None
        assert isinstance(IStreamProcessor, type)

    def test_istream_assembler_importable(self):
        """IStreamAssembler should be importable."""
        assert IStreamAssembler is not None
        assert isinstance(IStreamAssembler, type)

    def test_sentinel_manager_importable(self):
        """SentinelManager should be importable."""
        assert SentinelManager is not None
        assert isinstance(SentinelManager, type)

    def test_streaming_error_mapper_importable(self):
        """StreamingErrorMapper should be importable."""
        assert StreamingErrorMapper is not None
        assert isinstance(StreamingErrorMapper, type)

    def test_handle_streaming_error_importable(self):
        """handle_streaming_error should be importable."""
        assert handle_streaming_error is not None
        assert callable(handle_streaming_error)


class TestStopChunkUsageProtection:
    """Test stop-chunk usage protection invariants."""

    def test_stop_chunk_prevents_stringification(self):
        """StopChunkWithUsage should raise error on str() conversion."""
        chunk = StopChunkWithUsage(
            {
                "id": "test-123",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

        with pytest.raises(UsageChunkLeakError):
            str(chunk)

    def test_stop_chunk_prevents_json_dumps(self):
        """StopChunkWithUsage should raise TypeError on json.dumps()."""
        chunk = StopChunkWithUsage(
            {
                "id": "test-123",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

        with pytest.raises(TypeError):
            json.dumps(chunk)

    def test_stop_chunk_allows_explicit_dict_conversion(self):
        """StopChunkWithUsage should allow dict() conversion."""
        chunk_data = {
            "id": "test-123",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        chunk = StopChunkWithUsage(chunk_data)

        plain_dict = dict(chunk)
        assert plain_dict == chunk_data
        assert json.dumps(plain_dict)  # Should not raise

    def test_stop_chunk_safe_json_dumps(self):
        """StopChunkWithUsage.safe_json_dumps should work."""
        chunk = StopChunkWithUsage(
            {
                "id": "test-123",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

        json_str = StopChunkWithUsage.safe_json_dumps(chunk)
        parsed = json.loads(json_str)
        assert parsed["usage"]["prompt_tokens"] == 10


class TestSSEFramingInvariants:
    """Test SSE framing byte-level invariants."""

    def test_done_marker_exact_bytes(self):
        """Done marker must be exactly b'data: [DONE]\\n\\n'."""
        done_chunk = SentinelManager.create_done_chunk()
        assert done_chunk.is_done is True

        # Serialize and check exact bytes
        result_bytes = done_chunk.to_bytes()
        assert result_bytes == b"data: [DONE]\n\n"

    def test_stop_chunk_with_usage_serializes_correctly(self):
        """StopChunkWithUsage should serialize to SSE with usage at top level."""
        chunk_data = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        stop_chunk = StopChunkWithUsage(chunk_data)

        content = StreamingContent(
            content=stop_chunk,
            is_done=True,
            metadata={"finish_reason": "stop"},
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
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        assert len(json_lines) > 0
        main_json = json.loads(json_lines[0])

        # Verify usage is at top level
        assert "usage" in main_json
        assert main_json["usage"]["total_tokens"] == 150

        # Usage should NOT be in delta.content
        delta = main_json["choices"][0].get("delta", {})
        assert "content" not in delta or not delta.get("content")


class TestDoneMarkerHandling:
    """Test done marker handling invariants."""

    def test_sentinel_manager_creates_done_chunk(self):
        """SentinelManager.create_done_chunk should create proper done chunk."""
        done_chunk = SentinelManager.create_done_chunk()
        assert done_chunk.is_done is True
        assert done_chunk.content == "[DONE]"

    def test_sentinel_manager_detects_done(self):
        """SentinelManager.is_done_marker should detect done markers."""
        done_chunk = StreamingContent(content="[DONE]", is_done=True)
        assert SentinelManager.is_done_marker(done_chunk) is True

        normal_chunk = StreamingContent(content="Hello", is_done=False)
        assert SentinelManager.is_done_marker(normal_chunk) is False


class TestStreamingContentInvariants:
    """Test StreamingContent behavioral invariants."""

    def test_streaming_content_whitespace_preservation(self):
        """Whitespace-only deltas should be preserved."""
        whitespace_content = StreamingContent(
            content="   ",  # Whitespace-only
            is_done=False,
            metadata={},
        )
        assert not whitespace_content.is_empty
        assert whitespace_content.content == "   "

    def test_streaming_content_from_raw_basic(self):
        """StreamingContent.from_raw should parse basic content."""
        # Test with a simple string
        content = StreamingContent.from_raw("Hello")
        assert content.content == "Hello"
        assert not content.is_done

    def test_streaming_content_to_bytes_basic(self):
        """StreamingContent.to_bytes should serialize basic content."""
        content = StreamingContent(content="Hello", is_done=False)
        result = content.to_bytes()
        assert isinstance(result, bytes)
        assert b"data: " in result


class TestErrorMappingInvariants:
    """Test error mapping behavioral invariants."""

    def test_streaming_error_mapper_exists(self):
        """StreamingErrorMapper should have map_backend_error method."""
        assert hasattr(StreamingErrorMapper, "map_backend_error")
        assert callable(StreamingErrorMapper.map_backend_error)

    @pytest.mark.asyncio
    async def test_handle_streaming_error_returns_streaming_content(self):
        """handle_streaming_error should return StreamingContent."""
        error = ValueError("Test error")
        result = await handle_streaming_error(
            error, stream_id="test-123", provider="test"
        )

        assert isinstance(result, StreamingContent)
        assert result.is_done is True
        assert result.metadata.get("finish_reason") == "error"
        assert "error" in result.metadata
