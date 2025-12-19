"""Unit tests for ResponseFilter service.

Tests cover filtering reasoning tags from various content types and streaming responses.

Requirements satisfied:
- Req 2.5: ResponseFilter extraction
- Req 11: Test-preserving migration
"""

import json
from unittest.mock import AsyncMock

import pytest
from src.connectors.hybrid_backend.protocols import IResponseFilter
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseFilter:
    """Test ResponseFilter service implementation."""

    @pytest.fixture
    def filter_service(self):
        """Create a ResponseFilter instance for testing."""
        from src.connectors.hybrid_backend.services.response_filter import (
            ResponseFilter,
        )

        return ResponseFilter()

    def test_filter_implements_protocol(self, filter_service):
        """Verify filter implements IResponseFilter protocol."""
        assert isinstance(filter_service, IResponseFilter)

    def test_filter_content_string_with_tags(self, filter_service):
        """Test filter_content() removes reasoning tags from string."""
        content = "<thinking>This is reasoning</thinking>Some response text"
        filtered = filter_service.filter_content(content)

        assert "<thinking>" not in filtered
        assert "</thinking>" not in filtered
        assert "This is reasoning" not in filtered
        assert "Some response text" in filtered

    def test_filter_content_string_no_tags(self, filter_service):
        """Test filter_content() preserves string without tags."""
        content = "Just plain text response"
        filtered = filter_service.filter_content(content)

        assert filtered == content

    def test_filter_content_dict(self, filter_service):
        """Test filter_content() filters reasoning tags from dict."""
        content = {
            "content": "<thinking>Reasoning</thinking>Response",
            "role": "assistant",
        }
        filtered = filter_service.filter_content(content)

        assert isinstance(filtered, dict)
        assert "<thinking>" not in filtered["content"]
        assert "Reasoning" not in filtered["content"]
        assert "Response" in filtered["content"]

    def test_filter_content_dict_with_reasoning_content_key(self, filter_service):
        """Test filter_content() removes reasoning_content key from dict."""
        content = {
            "content": "Response",
            "reasoning_content": "Some reasoning",
            "role": "assistant",
        }
        filtered = filter_service.filter_content(content)

        assert "reasoning_content" not in filtered
        assert "content" in filtered

    def test_filter_content_nested_dict(self, filter_service):
        """Test filter_content() filters nested dict structures."""
        content = {
            "choices": [
                {
                    "message": {
                        "content": "<thinking>Reasoning</thinking>Response",
                        "role": "assistant",
                    }
                }
            ]
        }
        filtered = filter_service.filter_content(content)

        assert "<thinking>" not in str(filtered)
        assert "Reasoning" not in str(filtered)

    def test_filter_content_list(self, filter_service):
        """Test filter_content() filters reasoning tags from list."""
        content = [
            "<thinking>Reasoning</thinking>",
            "Response text",
            {"content": "<reason>More reasoning</reason>Text"},
        ]
        filtered = filter_service.filter_content(content)

        assert isinstance(filtered, list)
        assert "<thinking>" not in str(filtered)
        assert "<reason>" not in str(filtered)

    def test_filter_content_bytes(self, filter_service):
        """Test filter_content() handles bytes content."""
        content = b"<thinking>Reasoning</thinking>Response"
        filtered = filter_service.filter_content(content)

        assert isinstance(filtered, bytes)
        assert b"<thinking>" not in filtered
        assert b"Reasoning" not in filtered
        assert b"Response" in filtered

    def test_filter_content_sse_chunk(self, filter_service):
        """Test filter_content() filters SSE data chunks."""
        payload = {"content": "<thinking>Reasoning</thinking>Response"}
        sse_content = f"data: {json.dumps(payload)}\n\n"
        filtered = filter_service.filter_content(sse_content)

        assert "data: " in filtered
        assert "<thinking>" not in filtered
        assert "Reasoning" not in filtered

    def test_filter_content_sse_done_marker(self, filter_service):
        """Test filter_content() preserves [DONE] markers."""
        content = "data: [DONE]\n\n"
        filtered = filter_service.filter_content(content)

        assert filtered == content

    def test_filter_content_empty_string(self, filter_service):
        """Test filter_content() handles empty string."""
        filtered = filter_service.filter_content("")

        assert filtered == ""

    def test_filter_content_instruction_prefix_removed(self, filter_service):
        """Test filter_content() removes instruction prefix."""
        content = (
            "Consider this reasoning when formulating your response:\n\n"
            "<thinking>Reasoning</thinking>Response"
        )
        filtered = filter_service.filter_content(content)

        assert "Consider this reasoning" not in filtered
        assert "<thinking>" not in filtered

    @pytest.mark.asyncio
    async def test_filter_stream_filters_chunks(self, filter_service):
        """Test filter_stream() filters reasoning tags from streaming response."""
        # Create mock chunks
        chunk1 = ProcessedResponse(
            content="<thinking>Reasoning</thinking>Response chunk 1",
            usage=None,
            metadata={},
        )
        chunk2 = ProcessedResponse(
            content="Response chunk 2",
            usage=None,
            metadata={"reasoning": "some reasoning"},
        )

        async def mock_stream():
            yield chunk1
            yield chunk2

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=None,
        )

        filtered_response = await filter_service.filter_stream(original_response)

        assert isinstance(filtered_response, StreamingResponseEnvelope)
        assert filtered_response.media_type == original_response.media_type
        assert filtered_response.headers == original_response.headers

        # Collect filtered chunks
        filtered_chunks = []
        async for chunk in filtered_response.content:
            filtered_chunks.append(chunk)

        assert len(filtered_chunks) == 2
        assert "<thinking>" not in filtered_chunks[0].content
        assert "Reasoning" not in filtered_chunks[0].content
        assert "Response chunk 1" in filtered_chunks[0].content
        assert "reasoning" not in filtered_chunks[1].metadata

    @pytest.mark.asyncio
    async def test_filter_stream_preserves_cancel_callback(self, filter_service):
        """Test filter_stream() preserves cancel_callback."""
        cancel_callback = AsyncMock()

        async def mock_stream():
            yield ProcessedResponse(content="test", usage=None, metadata={})

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=cancel_callback,
        )

        filtered_response = await filter_service.filter_stream(original_response)

        assert filtered_response.cancel_callback == cancel_callback

    @pytest.mark.asyncio
    async def test_filter_stream_removes_reasoning_metadata(self, filter_service):
        """Test filter_stream() removes reasoning-related metadata keys."""
        chunk = ProcessedResponse(
            content="Response",
            usage=None,
            metadata={
                "reasoning": "some reasoning",
                "reasoning_content": "content",
                "reasoning_format": "format",
                "other_key": "value",
            },
        )

        async def mock_stream():
            yield chunk

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=None,
        )

        filtered_response = await filter_service.filter_stream(original_response)

        filtered_chunks = []
        async for chunk in filtered_response.content:
            filtered_chunks.append(chunk)

        assert len(filtered_chunks) == 1
        assert "reasoning" not in filtered_chunks[0].metadata
        assert "reasoning_content" not in filtered_chunks[0].metadata
        assert "reasoning_format" not in filtered_chunks[0].metadata
        assert filtered_chunks[0].metadata["other_key"] == "value"
