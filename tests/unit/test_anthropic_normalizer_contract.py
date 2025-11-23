"""
Contract tests for Anthropic stream normalizer.

These tests verify that the Anthropic normalizer correctly handles all
Anthropic-specific event formats and maps metadata completely.

Feature: streaming-pipeline-refactor
Requirements: 8.2, 8.3
"""

import pytest
from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
from src.core.ports.streaming_contracts import SentinelManager, StreamingContent


class TestAnthropicStreamNormalizerContract:
    """Contract tests for Anthropic normalizer."""

    @pytest.fixture
    def normalizer(self) -> AnthropicStreamNormalizer:
        """Create an Anthropic normalizer instance."""
        return AnthropicStreamNormalizer()

    @pytest.mark.asyncio
    async def test_normalizes_message_start_event(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test normalization of message_start event."""
        # Arrange
        raw_chunk = (
            b"event: message_start\n"
            b'data: {"type":"message_start","message":{"id":"msg_123","type":"message","role":"assistant","model":"claude-3-opus-20240229","content":[]}}\n\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 1
        chunk = chunks[0]

        assert isinstance(chunk, StreamingContent)
        assert chunk.metadata["provider"] == "anthropic"
        assert chunk.metadata["role"] == "assistant"
        assert chunk.metadata["model"] == "claude-3-opus-20240229"
        assert chunk.metadata["id"] == "msg_123"
        assert chunk.stream_id == "msg_123"
        assert chunk.is_empty is True

    @pytest.mark.asyncio
    async def test_normalizes_text_delta_event(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test normalization of content_block_delta with text."""

        # Arrange
        async def mock_stream():
            # Start message
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            # Text delta
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2

        # First chunk is message_start
        assert chunks[0].metadata["role"] == "assistant"

        # Second chunk is text content
        assert chunks[1].content == "Hello"
        assert chunks[1].metadata["provider"] == "anthropic"
        assert chunks[1].metadata["index"] == 0
        assert chunks[1].stream_id == "msg_123"

    @pytest.mark.asyncio
    async def test_normalizes_multiple_text_deltas(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test normalization of multiple text delta events."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 3
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[1].content == "Hello"
        assert chunks[2].content == " world"

        # All chunks should have same stream_id
        for chunk in chunks:
            assert chunk.stream_id == "msg_123"
            assert chunk.metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_normalizes_message_delta_with_stop_reason(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test normalization of message_delta with stop_reason."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            yield (
                b"event: message_delta\n"
                b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":10}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2

        # Second chunk has finish_reason mapped from stop_reason
        assert chunks[1].metadata["finish_reason"] == "stop"
        assert chunks[1].is_done is True
        assert chunks[1].usage == {"output_tokens": 10}
        assert chunks[1].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_maps_stop_reason_to_finish_reason(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test mapping of various stop_reason values to finish_reason."""
        test_cases = [
            ("end_turn", "stop"),
            ("max_tokens", "length"),
            ("stop_sequence", "stop"),
            ("tool_use", "tool_calls"),
        ]

        for stop_reason, expected_finish_reason in test_cases:
            # Arrange
            def create_mock_stream(sr: str):
                async def mock_stream():
                    yield (
                        b"event: message_start\n"
                        b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
                    )
                    yield (
                        f"event: message_delta\n"
                        f'data: {{"type":"message_delta","delta":{{"stop_reason":"{sr}"}}}}\n\n'
                    ).encode()

                return mock_stream()

            # Act
            chunks = [
                chunk
                async for chunk in normalizer.normalize_stream(
                    create_mock_stream(stop_reason), "anthropic"
                )
            ]

            # Assert
            assert chunks[1].metadata["finish_reason"] == expected_finish_reason

    @pytest.mark.asyncio
    async def test_handles_message_stop_event(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of message_stop event."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )
            yield (
                b"event: message_delta\n"
                b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
            )
            yield (b"event: message_stop\n" b'data: {"type":"message_stop"}\n\n')

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 4

        # Last chunk is done marker
        assert chunks[3].is_done is True
        assert SentinelManager.is_done_marker(chunks[3])
        assert chunks[3].metadata["provider"] == "anthropic"
        assert chunks[3].stream_id == "msg_123"

    @pytest.mark.asyncio
    async def test_handles_tool_use_input_json_delta(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of input_json_delta for tool use."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"location\\""}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2
        assert chunks[1].content == '{"location"'
        assert chunks[1].metadata["delta_type"] == "input_json_delta"
        assert chunks[1].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_handles_content_block_start_and_stop(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of content_block_start and content_block_stop events."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            yield (
                b"event: content_block_start\n"
                b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )
            yield (
                b"event: content_block_stop\n"
                b'data: {"type":"content_block_stop","index":0}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        # content_block_start and content_block_stop don't emit chunks
        assert len(chunks) == 2
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[1].content == "Hello"

    @pytest.mark.asyncio
    async def test_handles_ping_event(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of ping events."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            yield (b"event: ping\n" b'data: {"type":"ping"}\n\n')
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        # Ping events should be ignored
        assert len(chunks) == 2
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[1].content == "Hello"

    @pytest.mark.asyncio
    async def test_handles_error_event(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of error events."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            yield (
                b"event: error\n"
                b'data: {"type":"error","error":{"type":"overloaded_error","message":"Server is overloaded"}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2

        # Second chunk is error
        assert chunks[1].is_done is True
        assert "error" in chunks[1].metadata
        assert chunks[1].metadata["finish_reason"] == "error"
        assert chunks[1].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_handles_stream_error(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of errors during streaming."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            raise Exception("Stream error")

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2

        # First chunk is message_start
        assert chunks[0].metadata["role"] == "assistant"

        # Second chunk is error
        assert chunks[1].is_done is True
        assert "error" in chunks[1].metadata
        assert chunks[1].metadata["finish_reason"] == "error"
        assert chunks[1].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_handles_malformed_json(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of malformed JSON in event data."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            )
            yield (b"event: content_block_delta\n" b"data: {invalid json\n\n")

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        # Malformed JSON should be skipped (logged as warning)
        assert len(chunks) == 1
        assert chunks[0].metadata["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_handles_string_input(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of string input (not bytes)."""
        # Arrange
        raw_chunk = (
            "event: message_start\n"
            'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 1
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[0].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_handles_crlf_line_endings(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of CRLF line endings in SSE."""
        # Arrange
        raw_chunk = (
            b"event: message_start\r\n"
            b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\r\n\r\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 1
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[0].metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_preserves_stream_id_across_chunks(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test that stream_id is preserved across all chunks."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n'
            )
            yield (
                b"event: message_delta\n"
                b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
            )
            yield (b"event: message_stop\n" b'data: {"type":"message_stop"}\n\n')

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 5

        # All chunks should have the same stream_id
        stream_id = chunks[0].stream_id
        assert stream_id == "msg_123"

        for chunk in chunks:
            assert chunk.stream_id == stream_id
            assert (
                chunk.metadata.get("stream_id") == stream_id
                or chunk.metadata.get("id") == stream_id
            )

    @pytest.mark.asyncio
    async def test_metadata_mapping_completeness(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test that all Anthropic metadata fields are mapped correctly."""

        # Arrange
        async def mock_stream():
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3-opus-20240229"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Test"}}\n\n'
            )
            yield (
                b"event: message_delta\n"
                b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}\n\n'
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 3

        # Verify message_start chunk
        assert chunks[0].metadata["provider"] == "anthropic"
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[0].metadata["model"] == "claude-3-opus-20240229"
        assert chunks[0].metadata["id"] == "msg_123"
        assert chunks[0].stream_id == "msg_123"

        # Verify content chunk
        assert chunks[1].content == "Test"
        assert chunks[1].metadata["provider"] == "anthropic"
        assert chunks[1].metadata["index"] == 0
        assert chunks[1].stream_id == "msg_123"

        # Verify finish chunk
        assert chunks[2].metadata["finish_reason"] == "stop"
        assert chunks[2].is_done is True
        assert chunks[2].usage == {"output_tokens": 5}

        # Verify all chunks pass validation
        for chunk in chunks:
            assert normalizer.validate_chunk(chunk)

    @pytest.mark.asyncio
    async def test_complete_streaming_session(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test a complete streaming session with multiple chunks."""

        # Arrange
        async def mock_stream():
            # Message start
            yield (
                b"event: message_start\n"
                b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant","model":"claude-3"}}\n\n'
            )
            # Content block start
            yield (
                b"event: content_block_start\n"
                b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n\n'
            )
            # Content deltas
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n'
            )
            yield (
                b"event: content_block_delta\n"
                b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"!"}}\n\n'
            )
            # Content block stop
            yield (
                b"event: content_block_stop\n"
                b'data: {"type":"content_block_stop","index":0}\n\n'
            )
            # Message delta with stop reason
            yield (
                b"event: message_delta\n"
                b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":15}}\n\n'
            )
            # Message stop
            yield (b"event: message_stop\n" b'data: {"type":"message_stop"}\n\n')

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 6

        # Message start chunk
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[0].is_empty is True

        # Content chunks
        assert chunks[1].content == "Hello"
        assert chunks[2].content == " world"
        assert chunks[3].content == "!"

        # Finish chunk
        assert chunks[4].metadata["finish_reason"] == "stop"
        assert chunks[4].is_done is True
        assert chunks[4].usage == {"output_tokens": 15}

        # Done sentinel
        assert chunks[5].is_done is True
        assert SentinelManager.is_done_marker(chunks[5])

        # All chunks have same stream_id
        stream_id = chunks[0].stream_id
        for chunk in chunks:
            assert chunk.stream_id == stream_id
            assert chunk.metadata["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_handles_multiple_events_in_single_message(
        self, normalizer: AnthropicStreamNormalizer
    ) -> None:
        """Test handling of multiple SSE events in a single message."""
        # Arrange
        raw_chunk = (
            b"event: message_start\n"
            b'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'
            b"event: content_block_delta\n"
            b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "anthropic")
        ]

        # Assert
        assert len(chunks) == 2
        assert chunks[0].metadata["role"] == "assistant"
        assert chunks[1].content == "Hello"
        assert chunks[0].metadata["provider"] == "anthropic"
        assert chunks[1].metadata["provider"] == "anthropic"
