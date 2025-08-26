"""
Tests for the ResponseProcessor service using Hypothesis for property-based testing.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.domain.chat import StreamingChatResponse
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class TestResponseProcessor:
    """Tests for the ResponseProcessor class."""

    @pytest.fixture
    def mock_app_state(self) -> Mock:
        """Create a mock ApplicationStateService."""
        app_state = Mock(spec=IApplicationState)
        app_state.get_use_streaming_pipeline.return_value = False
        return app_state

    @pytest.fixture
    def mock_stream_normalizer(self) -> Mock:
        """Create a mock StreamNormalizer."""
        normalizer = Mock(spec=StreamNormalizer)

        # The new StreamNormalizer only has process_stream, not normalize_streaming_response
        # We need to mock process_stream to return an async generator of StreamingContent
        async def mock_generator(
            *args, **kwargs
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(
                content="Hello",
                metadata={"model": "test-model", "session_id": "test-session"},
            )
            yield StreamingContent(
                content=" world",
                metadata={"model": "test-model", "session_id": "test-session"},
            )

        # Create an AsyncMock that returns the generator
        mock_process_stream = AsyncMock()
        mock_process_stream.return_value = mock_generator()
        normalizer.process_stream = mock_process_stream
        return normalizer

    @pytest.fixture
    def loop_detector(self) -> Mock:
        """Create a mock loop detector."""
        detector = Mock(spec=ILoopDetector)
        detector.check_for_loops = AsyncMock(return_value=Mock(has_loop=False))
        return detector

    @pytest.fixture
    def middleware(self) -> Mock:
        """Create a mock middleware."""
        mw = Mock(spec=IResponseMiddleware)
        mw.process = AsyncMock(
            side_effect=lambda response, session_id, context: response
        )
        return mw

    @pytest.mark.asyncio
    async def test_process_response_with_dict(self, mock_app_state: Mock) -> None:
        """Test processing a dictionary response."""
        response = {
            "id": "test-id",
            "model": "test-model",
            "choices": [{"message": {"content": "Hello from dict!"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8},
        }

        processor = ResponseProcessor(app_state=mock_app_state)
        result = await processor.process_response(response, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == "Hello from dict!"
        assert result.usage == {"prompt_tokens": 15, "completion_tokens": 8}
        assert result.metadata["model"] == "test-model"
        assert result.metadata["id"] == "test-id"

    @pytest.mark.asyncio
    async def test_process_response_with_string(self, mock_app_state: Mock) -> None:
        """Test processing a string response."""
        response = "Direct content"

        processor = ResponseProcessor(app_state=mock_app_state)
        result = await processor.process_response(response, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == "Direct content"
        assert result.usage is None

    @pytest.mark.asyncio
    async def test_process_response_with_loop_detection(
        self, mock_app_state: Mock, loop_detector: Mock
    ) -> None:
        """Test processing a response with loop detection enabled."""
        response = "Repeated content that might be a loop"

        # Configure loop detector to detect a loop
        loop_result = Mock(has_loop=True, pattern="Repeated", repetitions=5)
        loop_detector.check_for_loops = AsyncMock(return_value=loop_result)

        processor = ResponseProcessor(
            app_state=mock_app_state, loop_detector=loop_detector
        )

        # Should raise LoopDetectionError
        with pytest.raises(Exception) as exc_info:
            await processor.process_response(response, "test-session")

        assert "loop detected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_process_response_with_middleware(
        self, mock_app_state: Mock, middleware: Mock
    ) -> None:
        """Test processing a response with middleware."""
        response = {"choices": [{"message": {"content": "Test content"}}]}

        processor = ResponseProcessor(app_state=mock_app_state, middleware=[middleware])
        result = await processor.process_response(response, "test-session")

        # Check that middleware was called
        middleware.process.assert_called_once()
        assert isinstance(result, ProcessedResponse)
        assert result.content == "Test content"

    @pytest.mark.asyncio
    async def test_process_streaming_response_basic(self, mock_app_state: Mock) -> None:
        """Test processing a streaming response."""

        async def mock_stream() -> AsyncGenerator[dict[str, list[dict[str, dict[str, str]]]], None]:  # type: ignore
            yield {"choices": [{"delta": {"content": "Hello"}}]}
            yield {"choices": [{"delta": {"content": " world"}}]}
            yield {"choices": [{"delta": {"content": "!"}}]}

        # Create a custom stream normalizer for this test
        from src.core.domain.streaming_response_processor import StreamingContent

        async def mock_process_stream(*args, **kwargs):
            yield StreamingContent(
                content="Hello", metadata={"session_id": "test-session"}
            )
            yield StreamingContent(
                content=" world", metadata={"session_id": "test-session"}
            )
            yield StreamingContent(content="!", metadata={"session_id": "test-session"})

        # Create a mock stream normalizer
        mock_normalizer = Mock()
        mock_normalizer.process_stream = mock_process_stream

        processor = ResponseProcessor(
            app_state=mock_app_state, stream_normalizer=mock_normalizer
        )
        stream = processor.process_streaming_response(mock_stream(), "test-session")  # type: ignore

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 3
        assert results[0].content == "Hello"
        assert results[1].content == " world"
        assert results[2].content == "!"

    @pytest.mark.asyncio
    async def test_process_streaming_response_with_streaming_chat_response(
        self, mock_app_state: Mock
    ) -> None:
        """Test processing a streaming response with StreamingChatResponse objects."""

        async def mock_stream() -> AsyncGenerator[StreamingChatResponse, None]:  # type: ignore
            yield StreamingChatResponse(content="Hello", model="test-model")
            yield StreamingChatResponse(content=" world", model="test-model")

        # Create a custom stream normalizer for this test
        from src.core.domain.streaming_response_processor import StreamingContent

        async def mock_process_stream(*args, **kwargs):
            yield StreamingContent(
                content="Hello",
                metadata={"model": "test-model", "session_id": "test-session"},
            )
            yield StreamingContent(
                content=" world",
                metadata={"model": "test-model", "session_id": "test-session"},
            )

        # Create a mock stream normalizer
        mock_normalizer = Mock()
        mock_normalizer.process_stream = mock_process_stream

        processor = ResponseProcessor(
            app_state=mock_app_state, stream_normalizer=mock_normalizer
        )
        stream = processor.process_streaming_response(mock_stream(), "test-session")  # type: ignore

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 2
        assert results[0].content == "Hello"
        assert results[1].content == " world"

    @pytest.mark.asyncio
    async def test_process_streaming_response_with_bytes(
        self, mock_app_state: Mock
    ) -> None:
        """Test processing a streaming response with bytes."""

        async def mock_stream() -> AsyncGenerator[bytes, None]:  # type: ignore
            yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
            yield b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'

        # Create a custom stream normalizer for this test
        from src.core.domain.streaming_response_processor import StreamingContent

        async def mock_process_stream(*args, **kwargs):
            yield StreamingContent(
                content="Hello", metadata={"session_id": "test-session"}
            )
            yield StreamingContent(
                content=" world", metadata={"session_id": "test-session"}
            )

        # Create a mock stream normalizer
        mock_normalizer = Mock()
        mock_normalizer.process_stream = mock_process_stream

        processor = ResponseProcessor(
            app_state=mock_app_state, stream_normalizer=mock_normalizer
        )
        stream = processor.process_streaming_response(mock_stream(), "test-session")  # type: ignore

        results = []
        async for result in stream:
            results.append(result)

        assert len(results) == 2
        assert results[0].content == "Hello"
        assert results[1].content == " world"

    @pytest.mark.asyncio
    async def test_process_streaming_response_with_normalizer_enabled(
        self, mock_app_state: Mock
    ) -> None:
        """Test processing a streaming response with stream normalizer enabled."""
        mock_app_state.get_use_streaming_pipeline.return_value = True

        # Create a simple async generator for testing
        async def test_stream() -> (
            AsyncGenerator[dict[str, list[dict[str, dict[str, str]]]], None]
        ):
            yield {"choices": [{"delta": {"content": "Hello"}}]}
            yield {"choices": [{"delta": {"content": " world"}}]}

        # Create a custom stream normalizer for this test
        from src.core.domain.streaming_response_processor import StreamingContent

        async def mock_process_stream(*args, **kwargs):
            yield StreamingContent(
                content="Hello", metadata={"session_id": "test-session"}
            )
            yield StreamingContent(
                content=" world", metadata={"session_id": "test-session"}
            )

        # Create a mock stream normalizer with process_stream method
        mock_normalizer = Mock()
        mock_process_stream_mock = AsyncMock()
        mock_process_stream_mock.return_value = mock_process_stream()
        mock_normalizer.process_stream = mock_process_stream_mock

        # Create a simple async generator for testing
        test_stream_instance = test_stream()

        processor = ResponseProcessor(
            app_state=mock_app_state, stream_normalizer=mock_normalizer
        )
        stream = processor.process_streaming_response(
            test_stream_instance, "test-session"
        )

        results = []
        async for result in stream:
            results.append(result)

        # Verify process_stream was called with the correct arguments
        mock_normalizer.process_stream.assert_called_once_with(
            test_stream_instance, output_format="objects"
        )
        assert len(results) == 2
        assert results[0].content == "Hello"
        assert results[1].content == " world"

    @given(content=st.text(min_size=1, max_size=100))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @pytest.mark.asyncio
    async def test_process_response_with_various_string_content(
        self, mock_app_state: Mock, content: str
    ) -> None:
        """Property-based test for processing various string content."""
        processor = ResponseProcessor(app_state=mock_app_state)
        result = await processor.process_response(content, "test-session")

        assert isinstance(result, ProcessedResponse)
        assert result.content == content
        assert isinstance(result.metadata, dict)
