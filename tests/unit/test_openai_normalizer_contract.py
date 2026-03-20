"""
Contract tests for OpenAI stream normalizer.

These tests verify that the OpenAI normalizer correctly handles all
OpenAI-specific chunk formats and maps metadata completely.

Feature: streaming-pipeline-refactor
"""

import json

import pytest
from src.core.ports.openai_normalizer import OpenAIStreamNormalizer
from src.core.ports.streaming_contracts import SentinelManager, StreamingContent


class TestOpenAIStreamNormalizerContract:
    """Contract tests for OpenAI normalizer."""

    @pytest.fixture
    def normalizer(self) -> OpenAIStreamNormalizer:
        """Create an OpenAI normalizer instance."""
        return OpenAIStreamNormalizer()

    @pytest.mark.asyncio
    async def test_normalizes_simple_content_chunk(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of simple content chunk."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert isinstance(chunk, StreamingContent)
        assert chunk.content == "Hello"
        assert chunk.metadata["provider"] == "openai"
        assert chunk.metadata["model"] == "gpt-4"
        assert chunk.metadata["id"] == "chatcmpl-123"
        assert chunk.metadata["created"] == 1234567890
        assert chunk.metadata["index"] == 0
        assert chunk.is_done is False
        assert chunk.is_empty is False

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_role(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with role in delta."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"role":"assistant","content":"Hi"}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.content == "Hi"
        assert chunk.metadata["role"] == "assistant"
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_finish_reason(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with finish_reason."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.metadata["finish_reason"] == "stop"
        assert chunk.is_done is True
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_ignores_empty_finish_reason(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Empty finish_reason should not mark chunk as done."""
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":""}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.is_done is False
        assert "finish_reason" not in chunk.metadata

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_tool_calls(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with tool_calls."""
        # Arrange
        tool_calls = [
            {
                "index": 0,
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location":"NYC"}'},
            }
        ]
        raw_chunk = (
            b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"tool_calls":'
            + json.dumps(tool_calls).encode()
            + b"}}]}\n\n"
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert "tool_calls" in chunk.metadata
        assert chunk.metadata["tool_calls"] == tool_calls
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_ignores_null_tool_calls(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test that null tool_calls in delta are ignored (regression for zenmux backend)."""
        # Arrange - Some backends return tool_calls: null instead of omitting the field
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello","tool_calls":null}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert - Should not crash and tool_calls should NOT be in metadata
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.content == "Hello"
        assert "tool_calls" not in chunk.metadata
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_ignores_empty_tool_calls_list(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test that empty tool_calls list in delta is ignored."""
        # Arrange - Empty list should not be added to metadata
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello","tool_calls":[]}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert - Should not crash and empty tool_calls should NOT be in metadata
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.content == "Hello"
        assert "tool_calls" not in chunk.metadata
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_reasoning_content(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with reasoning_content."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"reasoning_content":"Let me think..."}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.metadata["reasoning_content"] == "Let me think..."
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_reasoning_field(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with reasoning field (alternative)."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"reasoning":"Thinking..."}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.metadata["reasoning_content"] == "Thinking..."
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_thinking_field(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test normalization of chunk with thinking field (alternative)."""
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"thinking":"Plan step."}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.metadata["reasoning_content"] == "Plan step."
        assert chunk.is_empty is False
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_message_fallback(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Use message content when delta content is empty."""
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":""},"message":{"content":"Hello"}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.content == "Hello"
        assert chunk.is_empty is False
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_reasoning_only_with_null_content(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Ensure chunks with null content but reasoning text are surfaced."""
        # Arrange - Some models emit only reasoning_content and null content
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":null,"reasoning_content":"Plan tools next"}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        # Reasoning should be preserved in metadata without leaking into main content
        assert chunk.content == ""
        assert chunk.metadata["reasoning_content"] == "Plan tools next"
        assert chunk.is_empty is False
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_done_sentinel(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of [DONE] sentinel."""

        # Arrange
        async def mock_stream():
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 2

        # First chunk is content
        assert chunks[0].content == "Hello"
        assert chunks[0].is_done is False

        # Second chunk is done marker
        assert chunks[1].is_done is True
        assert SentinelManager.is_done_marker(chunks[1])
        assert chunks[1].metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_multiple_chunks_in_single_message(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of multiple SSE events in a single message."""
        # Arrange
        raw_chunk = (
            b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
            b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":" world"}}]}\n\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 2
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[0].metadata["provider"] == "openai"
        assert chunks[1].metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_empty_choices(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of chunks with empty choices array."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        # Empty choices should be skipped
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_handles_content_without_choices(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Fallback to top-level content when choices are missing."""
        raw_chunk = b'data: {"id":"chatcmpl-123","content":"Hello"}\n\n'

        async def mock_stream():
            yield raw_chunk

        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.content == "Hello"
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_empty_delta(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of chunks with empty delta."""
        # Arrange
        raw_chunk = (
            b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{}}]}\n\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert chunk.content == ""
        assert chunk.is_empty is True
        assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_preserves_stream_id_across_chunks(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test that stream_id is preserved across all chunks."""

        # Arrange
        async def mock_stream():
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":" world"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 3

        # All chunks should have the same stream_id
        stream_id = chunks[0].stream_id
        assert stream_id == "chatcmpl-123"

        for chunk in chunks:
            assert chunk.stream_id == stream_id
            assert chunk.metadata.get("stream_id") == stream_id

    @pytest.mark.asyncio
    async def test_handles_string_input(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of string input (not bytes)."""
        # Arrange
        raw_chunk = 'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        assert chunks[0].content == "Hello"
        assert chunks[0].metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_handles_malformed_json(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of malformed JSON."""
        # Arrange
        raw_chunk = b'data: {"invalid json\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        # Malformed JSON should be skipped (logged as warning)
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_handles_stream_error(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of errors during streaming."""

        # Arrange
        async def mock_stream():
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
            raise Exception("Stream error")

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 2

        # First chunk is content
        assert chunks[0].content == "Hello"
        assert chunks[0].is_done is False

        # Second chunk is error
        assert chunks[1].is_done is True
        assert "error" in chunks[1].metadata
        assert chunks[1].metadata["finish_reason"] == "error"
        assert chunks[1].metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_metadata_mapping_completeness(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test that all OpenAI metadata fields are mapped correctly."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":"Test","tool_call_id":"call_456"},"finish_reason":"stop"}]}\n\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        # Verify all metadata fields are present
        assert chunk.metadata["provider"] == "openai"
        assert chunk.metadata["model"] == "gpt-4"
        assert chunk.metadata["id"] == "chatcmpl-123"
        assert chunk.metadata["created"] == 1234567890
        assert chunk.metadata["role"] == "assistant"
        assert chunk.metadata["finish_reason"] == "stop"
        assert chunk.metadata["tool_call_id"] == "call_456"
        assert chunk.metadata["index"] == 0
        assert chunk.metadata["stream_id"] == "chatcmpl-123"

        # Verify chunk passes validation
        assert normalizer.validate_chunk(chunk)

    @pytest.mark.asyncio
    async def test_handles_crlf_line_endings(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test handling of CRLF line endings in SSE."""
        # Arrange
        raw_chunk = b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\r\n\r\n'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 1
        assert chunks[0].content == "Hello"
        assert chunks[0].metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_complete_streaming_session(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Test a complete streaming session with multiple chunks."""

        # Arrange
        async def mock_stream():
            # Initial chunk with role
            yield b'data: {"id":"chatcmpl-123","model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n'
            # Content chunks
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":" world"}}]}\n\n'
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{"content":"!"}}]}\n\n'
            # Final chunk with finish_reason
            yield b'data: {"id":"chatcmpl-123","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            # Done sentinel
            yield b"data: [DONE]\n\n"

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "openai")
        ]

        # Assert
        assert len(chunks) == 6

        # First chunk has role
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[0].is_done is False

        # Content chunks
        assert chunks[1].content == "Hello"
        assert chunks[2].content == " world"
        assert chunks[3].content == "!"

        # Finish chunk
        assert chunks[4].metadata["finish_reason"] == "stop"
        assert chunks[4].is_done is True

        # Done sentinel
        assert chunks[5].is_done is True
        assert SentinelManager.is_done_marker(chunks[5])

        # All chunks have same stream_id
        stream_id = chunks[0].stream_id
        for chunk in chunks:
            assert chunk.stream_id == stream_id
            assert chunk.metadata["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_tool_calls_with_null_id_passes_validation(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """OpenAI-compatible streams may send id: null on early tool_call deltas."""
        payload = {
            "id": "chatcmpl-x",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": None,
                                "type": "function",
                                "function": {
                                    "name": "attempt_completion",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    },
                }
            ],
        }
        raw = f"data: {json.dumps(payload)}\n\n".encode()

        async def mock_stream():
            yield raw

        chunks = [c async for c in normalizer.normalize_stream(mock_stream(), "openai")]
        assert len(chunks) == 1
        assert normalizer.validate_chunk(chunks[0])
        tc0 = chunks[0].metadata["tool_calls"][0]
        assert "id" not in tc0

    @pytest.mark.asyncio
    async def test_tool_calls_numeric_id_coerced_to_str(
        self, normalizer: OpenAIStreamNormalizer
    ) -> None:
        """Some backends emit non-string tool_call ids."""
        payload = {
            "id": "chatcmpl-x",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": 42,
                                "type": "function",
                                "function": {"name": "x", "arguments": ""},
                            }
                        ]
                    },
                }
            ],
        }
        raw = f"data: {json.dumps(payload)}\n\n".encode()

        async def mock_stream():
            yield raw

        chunks = [c async for c in normalizer.normalize_stream(mock_stream(), "openai")]
        assert len(chunks) == 1
        assert normalizer.validate_chunk(chunks[0])
        assert chunks[0].metadata["tool_calls"][0]["id"] == "42"
