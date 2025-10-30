"""Tests for Anthropic streaming chunk translation with SSE format support."""

from src.core.domain.translation import Translation


class TestAnthropicStreamingTranslation:
    """Test suite for Anthropic SSE streaming chunk translation."""

    def test_anthropic_sse_content_delta(self):
        """Test translation of Anthropic content_block_delta SSE event."""
        sse_chunk = 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"]["content"] == "Hello"
        assert result["choices"][0]["finish_reason"] is None

    def test_anthropic_sse_message_start(self):
        """Test translation of Anthropic message_start SSE event."""
        sse_chunk = 'data: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n'

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"]["role"] == "assistant"

    def test_anthropic_sse_message_delta_stop(self):
        """Test translation of Anthropic message_delta with stop_reason."""
        sse_chunk = (
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
        )

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_anthropic_sse_message_delta_max_tokens(self):
        """Test translation of Anthropic message_delta with max_tokens stop reason."""
        sse_chunk = (
            'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}\n\n'
        )

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["choices"][0]["finish_reason"] == "length"

    def test_anthropic_sse_message_stop(self):
        """Test translation of Anthropic message_stop SSE event."""
        sse_chunk = 'data: {"type":"message_stop"}\n\n'

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_anthropic_sse_done_marker(self):
        """Test translation of [DONE] marker."""
        sse_chunk = "data: [DONE]\n\n"

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"] == {}

    def test_anthropic_sse_event_line_ignored(self):
        """Test that event: lines are handled gracefully."""
        sse_chunk = "event: content_block_delta\n"

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        # Should return empty delta for event lines
        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"] == {}

    def test_anthropic_sse_without_data_prefix(self):
        """Test parsing SSE chunk without 'data:' prefix."""
        sse_chunk = (
            '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Test"}}'
        )

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["choices"][0]["delta"]["content"] == "Test"

    def test_anthropic_dict_format_backward_compatibility(self):
        """Test that dict format (non-SSE) still works for backward compatibility."""
        chunk_dict = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
        }

        result = Translation.anthropic_to_domain_stream_chunk(chunk_dict)

        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"]["content"] == "Hello"

    def test_anthropic_invalid_json_in_sse(self):
        """Test handling of invalid JSON in SSE data."""
        sse_chunk = "data: {invalid json}\n\n"

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert "error" in result
        assert result["error"] == "Invalid chunk format: expected a dictionary"

    def test_anthropic_multiple_content_deltas(self):
        """Test multiple content deltas produce correct content."""
        chunks = [
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" "}}\n\n',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"world"}}\n\n',
        ]

        results = [
            Translation.anthropic_to_domain_stream_chunk(chunk) for chunk in chunks
        ]

        # Collect content
        content_parts = [r["choices"][0]["delta"].get("content", "") for r in results]
        full_content = "".join(content_parts)

        assert full_content == "Hello world"

    def test_anthropic_content_block_start_and_stop(self):
        """Test content_block_start and content_block_stop events."""
        start_chunk = 'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        stop_chunk = 'data: {"type":"content_block_stop","index":0}\n\n'

        start_result = Translation.anthropic_to_domain_stream_chunk(start_chunk)
        stop_result = Translation.anthropic_to_domain_stream_chunk(stop_chunk)

        # These events should produce valid chunks with empty deltas
        assert start_result["object"] == "chat.completion.chunk"
        assert stop_result["object"] == "chat.completion.chunk"

    def test_anthropic_streaming_preserves_structure(self):
        """Test that all required OpenAI fields are present."""
        sse_chunk = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Test"}}\n\n'

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        # Verify OpenAI-compatible structure
        assert "id" in result
        assert "object" in result
        assert "created" in result
        assert "model" in result
        assert "choices" in result
        assert len(result["choices"]) == 1

        choice = result["choices"][0]
        assert "index" in choice
        assert choice["index"] == 0
        assert "delta" in choice
        assert "finish_reason" in choice

    def test_anthropic_tool_use_stop_reason(self):
        """Test translation of tool_use stop reason."""
        sse_chunk = (
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"}}\n\n'
        )

        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        assert result["choices"][0]["finish_reason"] == "tool_calls"

    def test_anthropic_empty_string_chunk(self):
        """Test handling of empty string chunks."""
        result = Translation.anthropic_to_domain_stream_chunk("")

        # Should return empty delta for empty chunks
        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"] == {}

    def test_anthropic_whitespace_only_chunk(self):
        """Test handling of whitespace-only chunks."""
        result = Translation.anthropic_to_domain_stream_chunk("   \n\n  ")

        # Should return empty delta for whitespace chunks
        assert result["object"] == "chat.completion.chunk"
        assert result["choices"][0]["delta"] == {}
