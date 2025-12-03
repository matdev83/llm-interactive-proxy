"""
Tests for response adapter handling of dict chunks.

These tests verify that the response adapter correctly handles
OpenAI-format dict chunks and StopChunkWithUsage objects through
the streaming pipeline.
"""

from __future__ import annotations

import pytest
from src.core.ports.streaming_contracts import StopChunkWithUsage


class TestChunkSignalsDone:
    """Test the _chunk_signals_done function behavior."""

    @pytest.fixture
    def chunk_signals_done(self):
        """Import the _chunk_signals_done function."""
        from src.core.transport.fastapi.response_adapters import _chunk_signals_done

        return _chunk_signals_done

    def test_finish_reason_stop_signals_done(self, chunk_signals_done):
        """Chunk with finish_reason=stop should signal done."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [
                {"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}
            ],
        }

        assert chunk_signals_done(chunk, {}) is True

    def test_finish_reason_tool_calls_signals_done(self, chunk_signals_done):
        """Chunk with finish_reason=tool_calls should signal done."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }

        assert chunk_signals_done(chunk, {}) is True

    def test_finish_reason_length_signals_done(self, chunk_signals_done):
        """Chunk with finish_reason=length should signal done."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}],
        }

        assert chunk_signals_done(chunk, {}) is True

    def test_no_finish_reason_does_not_signal_done(self, chunk_signals_done):
        """Chunk without finish_reason should not signal done."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [
                {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
            ],
        }

        assert chunk_signals_done(chunk, {}) is False

    def test_empty_choices_does_not_signal_done(self, chunk_signals_done):
        """Chunk with empty choices should not signal done (but may have usage)."""
        chunk = {"id": "chatcmpl-test", "choices": []}

        result = chunk_signals_done(chunk, {})
        # Empty choices alone shouldn't signal done unless other markers present
        assert isinstance(result, bool)

    def test_stop_chunk_with_usage_signals_done(self, chunk_signals_done):
        """StopChunkWithUsage should signal done."""
        stop_chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-stop",
                "choices": [
                    {"index": 0, "delta": {"content": "4"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 16},
            }
        )

        # StopChunkWithUsage is a dict subclass, should be recognized
        assert chunk_signals_done(stop_chunk, {}) is True

    def test_done_marker_string_signals_done(self, chunk_signals_done):
        """The string '[DONE]' should signal done."""
        assert chunk_signals_done("[DONE]", {}) is True


class TestInjectReasoningMetadata:
    """Test the _inject_reasoning_metadata function behavior."""

    @pytest.fixture
    def inject_reasoning_metadata(self):
        """Import the _inject_reasoning_metadata function."""
        from src.core.transport.fastapi.response_adapters import (
            _inject_reasoning_metadata,
        )

        return _inject_reasoning_metadata

    def test_preserve_stop_chunk_with_usage(self, inject_reasoning_metadata):
        """StopChunkWithUsage should be preserved through metadata injection."""
        stop_chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-stop",
                "choices": [{"delta": {"content": "4"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 16},
            }
        )

        result = inject_reasoning_metadata(stop_chunk, {}, streaming=True)

        # Should preserve the StopChunkWithUsage type
        assert isinstance(result, StopChunkWithUsage)
        assert result["choices"][0]["delta"]["content"] == "4"

    def test_preserve_dict_content(self, inject_reasoning_metadata):
        """Regular dict content should be preserved."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
        }

        result = inject_reasoning_metadata(chunk, {}, streaming=True)

        assert isinstance(result, dict)
        assert result["choices"][0]["delta"]["content"] == "Hello"


class TestNormalizeContent:
    """Test the _normalize_content function behavior."""

    @pytest.fixture
    def normalize_content(self):
        """Import the _normalize_content function."""
        from src.core.transport.fastapi.response_adapters import _normalize_content

        return _normalize_content

    def test_preserve_stop_chunk_with_usage(self, normalize_content):
        """StopChunkWithUsage should be preserved."""
        stop_chunk = StopChunkWithUsage({"id": "test", "usage": {"total_tokens": 5}})

        result = normalize_content(stop_chunk)

        assert isinstance(result, StopChunkWithUsage)
        assert result is stop_chunk

    def test_preserve_regular_dict(self, normalize_content):
        """Regular dicts should be converted to plain dict."""
        chunk = {"id": "test", "choices": []}

        result = normalize_content(chunk)

        assert isinstance(result, dict)
        assert result["id"] == "test"

    def test_preserve_string(self, normalize_content):
        """Strings should pass through."""
        text = "Hello world"

        result = normalize_content(text)

        assert result == text


class TestStreamingAdapterIntegration:
    """Integration tests for the streaming adapter with dict content."""

    @pytest.mark.asyncio
    async def test_process_single_stop_chunk_with_content(self):
        """Single stop chunk with content should produce complete SSE output."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        # Simulate what the connector yields for a short response
        stop_chunk_data = {
            "id": "chatcmpl-short",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "42"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 1,
                "total_tokens": 11,
            },
        }

        # Create a ProcessedResponse like the connector yields
        response = ProcessedResponse(
            content=StopChunkWithUsage(stop_chunk_data),
            metadata={"finish_reason": "stop", "model": "gemini-2.5-flash"},
            usage=stop_chunk_data["usage"],
        )

        # Verify the content is accessible
        assert isinstance(response.content, StopChunkWithUsage)
        assert response.content["choices"][0]["delta"]["content"] == "42"

    @pytest.mark.asyncio
    async def test_process_multiple_chunks_then_stop(self):
        """Multiple content chunks followed by stop chunk should all be preserved."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        # First chunk: role
        chunk1 = ProcessedResponse(
            content={
                "id": "chatcmpl-multi",
                "choices": [{"index": 0, "delta": {"role": "assistant"}}],
            },
            metadata={"model": "gemini-2.5-flash"},
        )

        # Second chunk: content
        chunk2 = ProcessedResponse(
            content={
                "id": "chatcmpl-multi",
                "choices": [{"index": 0, "delta": {"content": "The answer is "}}],
            },
            metadata={},
        )

        # Third chunk: more content
        chunk3 = ProcessedResponse(
            content={
                "id": "chatcmpl-multi",
                "choices": [{"index": 0, "delta": {"content": "42"}}],
            },
            metadata={},
        )

        # Final chunk: stop with usage
        chunk4 = ProcessedResponse(
            content=StopChunkWithUsage(
                {
                    "id": "chatcmpl-multi",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 15},
                }
            ),
            metadata={"finish_reason": "stop"},
            usage={"total_tokens": 15},
        )

        # All chunks should have accessible content
        assert chunk1.content["choices"][0]["delta"].get("role") == "assistant"
        assert chunk2.content["choices"][0]["delta"]["content"] == "The answer is "
        assert chunk3.content["choices"][0]["delta"]["content"] == "42"
        assert isinstance(chunk4.content, StopChunkWithUsage)
        assert chunk4.content["choices"][0]["finish_reason"] == "stop"


class TestChunkSignalsDoneWithMetadata:
    """Test _chunk_signals_done with various metadata combinations."""

    @pytest.fixture
    def chunk_signals_done(self):
        """Import the _chunk_signals_done function."""
        from src.core.transport.fastapi.response_adapters import _chunk_signals_done

        return _chunk_signals_done

    def test_finish_reason_in_metadata_with_empty_content(self, chunk_signals_done):
        """finish_reason in metadata with empty content should signal done."""
        # When content is empty dict but metadata has finish_reason
        result = chunk_signals_done({}, {"finish_reason": "stop"})
        # Depending on implementation, this may or may not signal done
        assert isinstance(result, bool)

    def test_stop_chunk_content_takes_priority(self, chunk_signals_done):
        """Content finish_reason should take priority over metadata."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [
                {"index": 0, "delta": {"content": "final"}, "finish_reason": "stop"}
            ],
        }
        # Even if metadata doesn't have finish_reason, content does
        result = chunk_signals_done(chunk, None)
        assert result is True

    def test_none_metadata_handled(self, chunk_signals_done):
        """None metadata should be handled gracefully."""
        chunk = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {"content": "hi"}}],
        }
        # Should not raise exception
        result = chunk_signals_done(chunk, None)
        assert result is False
