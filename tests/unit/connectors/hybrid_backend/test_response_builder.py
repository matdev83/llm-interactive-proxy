"""Unit tests for ResponseBuilder service.

Tests cover building reasoning chunks, tool-call responses, and prepending reasoning to streams.

Requirements satisfied:
- Req 2.6: ResponseBuilder extraction
- Req 11: Test-preserving migration
"""

from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.hybrid_backend.protocols import (
    IReasoningMarkupProcessor,
    IResponseBuilder,
)
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseBuilder:
    """Test ResponseBuilder service implementation."""

    @pytest.fixture
    def mock_markup_processor(self):
        """Create a mock ReasoningMarkupProcessor."""
        mock = Mock(spec=IReasoningMarkupProcessor)
        mock.format_for_model.return_value = "<thinking>Reasoning</thinking>"
        mock.extract_plain_text.return_value = "Reasoning"
        return mock

    @pytest.fixture
    def builder(self, mock_markup_processor):
        """Create a ResponseBuilder instance for testing."""
        from src.connectors.hybrid_backend.services.response_builder import (
            ResponseBuilder,
        )

        return ResponseBuilder(markup_processor=mock_markup_processor)

    def test_builder_implements_protocol(self, builder):
        """Verify builder implements IResponseBuilder protocol."""
        assert isinstance(builder, IResponseBuilder)

    def test_build_reasoning_chunk_creates_chunk(self, builder, mock_markup_processor):
        """Test build_reasoning_chunk() creates ProcessedResponse chunk."""
        reasoning_output = "Some reasoning text"
        chunk = builder.build_reasoning_chunk(reasoning_output, "openai", "gpt-4")

        assert chunk is not None
        assert isinstance(chunk, ProcessedResponse)
        assert chunk.content
        assert "data: " in chunk.content
        assert "reasoning" in chunk.content.lower()
        mock_markup_processor.format_for_model.assert_called()

    def test_build_reasoning_chunk_returns_none_if_no_content(
        self, builder, mock_markup_processor
    ):
        """Test build_reasoning_chunk() returns None if no reasoning content."""
        mock_markup_processor.format_for_model.return_value = ""
        mock_markup_processor.extract_plain_text.return_value = ""

        chunk = builder.build_reasoning_chunk("", "openai", "gpt-4")

        assert chunk is None

    def test_build_reasoning_chunk_includes_metadata(self, builder):
        """Test build_reasoning_chunk() includes hybrid phase metadata."""
        chunk = builder.build_reasoning_chunk("reasoning", "openai", "gpt-4")

        assert chunk is not None
        assert chunk.metadata["hybrid_phase"] == "reasoning"
        assert chunk.metadata["reasoning_backend"] == "openai"
        assert chunk.metadata["reasoning_model"] == "gpt-4"

    def test_build_tool_call_response_streaming(self, builder):
        """Test build_tool_call_response() creates streaming response for tool calls."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "test_function", "arguments": '{"arg": "value"}'},
            }
        ]
        request_dict = {"stream": True}

        response = builder.build_tool_call_response(
            tool_calls, request_dict, "openai", "gpt-4"
        )

        assert isinstance(response, StreamingResponseEnvelope)
        assert response.media_type == "text/event-stream"

    def test_build_tool_call_response_non_streaming(self, builder):
        """Test build_tool_call_response() creates non-streaming response for tool calls."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "test_function", "arguments": '{"arg": "value"}'},
            }
        ]
        request_dict = {"stream": False}

        response = builder.build_tool_call_response(
            tool_calls, request_dict, "openai", "gpt-4"
        )

        from src.core.domain.responses import ResponseEnvelope

        assert isinstance(response, ResponseEnvelope)
        assert response.content
        assert response.content["choices"][0]["message"]["tool_calls"] == tool_calls

    @pytest.mark.asyncio
    async def test_prepend_reasoning_to_stream_prepends_chunk(self, builder):
        """Test prepend_reasoning_to_stream() prepends reasoning chunk to stream."""

        # Create mock stream
        async def mock_stream():
            yield ProcessedResponse(
                content='data: {"content": "Response"}\n\n',
                usage=None,
                metadata={},
            )

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=None,
        )

        result = builder.prepend_reasoning_to_stream(
            original_response, "reasoning", "openai", "gpt-4"
        )

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == original_response.media_type

        # Collect chunks
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)

        assert len(chunks) >= 2  # Reasoning chunk + original chunks
        assert "reasoning" in chunks[0].content.lower()

    @pytest.mark.asyncio
    async def test_prepend_reasoning_to_stream_preserves_cancel_callback(self, builder):
        """Test prepend_reasoning_to_stream() preserves cancel_callback."""
        cancel_callback = AsyncMock()

        async def mock_stream():
            yield ProcessedResponse(content="test", usage=None, metadata={})

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=cancel_callback,
        )

        result = builder.prepend_reasoning_to_stream(
            original_response, "reasoning", "openai", "gpt-4"
        )

        assert result.cancel_callback == cancel_callback

    @pytest.mark.asyncio
    async def test_prepend_reasoning_to_stream_returns_original_if_no_reasoning(
        self, builder, mock_markup_processor
    ):
        """Test prepend_reasoning_to_stream() returns original if no reasoning content."""
        mock_markup_processor.format_for_model.return_value = ""
        mock_markup_processor.extract_plain_text.return_value = ""

        async def mock_stream():
            yield ProcessedResponse(content="test", usage=None, metadata={})

        original_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
            headers={},
            cancel_callback=None,
        )

        result = builder.prepend_reasoning_to_stream(
            original_response, "", "openai", "gpt-4"
        )

        assert result == original_response

    def test_build_tool_call_response_includes_metadata(self, builder):
        """Test build_tool_call_response() includes hybrid phase metadata."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "test_function", "arguments": '{"arg": "value"}'},
            }
        ]
        request_dict = {"stream": False}

        response = builder.build_tool_call_response(
            tool_calls, request_dict, "openai", "gpt-4"
        )

        assert response.metadata["hybrid_phase"] == "reasoning"
        assert response.metadata["reasoning_backend"] == "openai"
        assert response.metadata["skipped_execution"] is True
