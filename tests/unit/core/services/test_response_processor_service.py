"""
Tests for the ResponseProcessor service using Hypothesis for property-based testing.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.chat import StreamingChatResponse
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.response_processor_service import ResponseProcessor


class TestResponseProcessor:
    """Tests for the ResponseProcessor class."""

    @pytest.fixture
    def loop_detector(self):
        """Create a mock loop detector."""
        detector = Mock(spec=ILoopDetector)
        detector.check_for_loops = AsyncMock(return_value=Mock(has_loop=False))
        return detector

    @pytest.fixture
    def middleware(self):
        """Create a mock middleware."""
        mw = Mock(spec=IResponseMiddleware)
        mw.process = AsyncMock(
            side_effect=lambda response, session_id, context: response
        )
        return mw

    @pytest.mark.asyncio
    async def test_process_response_with_dict(self) -> None:
        """Test processing a dictionary response."""
        response = {
            "id": "test-id",
            "model": "test-model",
            "choices": [{"message": {"content": "Hello from dict!"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8},
        }

        processor = ResponseProcessor()
        result = await processor.process_response(response, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == "Hello from dict!"
        assert result.usage == {"prompt_tokens": 15, "completion_tokens": 8}
        assert result.metadata["model"] == "test-model"
        assert result.metadata["id"] == "test-id"

    @pytest.mark.asyncio
    async def test_process_response_with_string(self) -> None:
        """Test processing a string response."""
        response = "Direct content"

        processor = ResponseProcessor()
        result = await processor.process_response(response, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == "Direct content"
        assert result.usage is None

    @pytest.mark.asyncio
    async def test_process_response_with_loop_detection(self, loop_detector) -> None:
        """Test processing a response with loop detection enabled."""
        response = "Repeated content that might be a loop"

        # Configure loop detector to detect a loop
        loop_result = Mock(has_loop=True, pattern="Repeated", repetitions=5)
        loop_detector.check_for_loops = AsyncMock(return_value=loop_result)

        processor = ResponseProcessor(loop_detector=loop_detector)

        # Should raise LoopDetectionError
        with pytest.raises(Exception) as exc_info:
            await processor.process_response(response, "test-session")

        assert "loop detected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_process_response_with_middleware(self, middleware) -> None:
        """Test processing a response with middleware."""
        response = {"choices": [{"message": {"content": "Test content"}}]}

        processor = ResponseProcessor(middleware=[middleware])
        result = await processor.process_response(response, "test-session")

        # Check that middleware was called
        middleware.process.assert_called_once()
        assert isinstance(result, ProcessedResponse)
        assert result.content == "Test content"

    @pytest.mark.asyncio
    async def test_process_streaming_response_basic(self) -> None:
        """Test processing a streaming response."""

        async def mock_stream():
            yield {"choices": [{"delta": {"content": "Hello"}}]}
            yield {"choices": [{"delta": {"content": " world"}}]}
            yield {"choices": [{"delta": {"content": "!"}}]}

        processor = ResponseProcessor()
        stream = processor.process_streaming_response(mock_stream(), "test-session")

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 3
        assert results[0].content == "Hello"
        assert results[1].content == " world"
        assert results[2].content == "!"

    @pytest.mark.asyncio
    async def test_process_streaming_response_with_streaming_chat_response(
        self,
    ) -> None:
        """Test processing a streaming response with StreamingChatResponse objects."""

        async def mock_stream():
            yield StreamingChatResponse(content="Hello", model="test-model")
            yield StreamingChatResponse(content=" world", model="test-model")

        processor = ResponseProcessor()
        stream = processor.process_streaming_response(mock_stream(), "test-session")

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 2
        assert results[0].content == "Hello"
        assert results[1].content == " world"

    @pytest.mark.asyncio
    async def test_process_streaming_response_with_bytes(self) -> None:
        """Test processing a streaming response with bytes."""

        async def mock_stream():
            yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'

        processor = ResponseProcessor()
        stream = processor.process_streaming_response(mock_stream(), "test-session")

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 2
        assert "Hello" in results[0].content
        assert "world" in results[1].content

    @given(content=st.text(min_size=1, max_size=100))
    @pytest.mark.asyncio
    async def test_process_response_with_various_string_content(self, content) -> None:
        """Property-based test for processing various string content."""
        processor = ResponseProcessor()
        result = await processor.process_response(content, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == content
        assert isinstance(result.metadata, dict)
