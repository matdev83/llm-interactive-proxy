from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.common.exceptions import LoopDetectionError, ParsingError
from src.core.domain.chat import StreamingChatResponse
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.services.response_processor_service import ResponseProcessor


@pytest.fixture
def mock_response_parser() -> MagicMock:
    """Fixture for a mock response parser."""
    parser = MagicMock(spec=IResponseParser)
    parser.parse_response.return_value = {}
    parser.extract_content.return_value = "default content"
    parser.extract_usage.return_value = None
    parser.extract_metadata.return_value = {}
    return parser


@pytest.fixture
def mock_middleware_application_manager() -> AsyncMock:
    """Fixture for a mock middleware application manager."""
    manager = AsyncMock(spec=IMiddlewareApplicationManager)
    manager.apply_middleware.side_effect = lambda content, **kwargs: content
    return manager


@pytest.fixture
def mock_loop_detector() -> AsyncMock:
    """Fixture for a mock loop detector."""
    detector = AsyncMock(spec=ILoopDetector)
    detector.check_for_loops.return_value = MagicMock(has_loop=False)
    return detector


@pytest.fixture
def mock_stream_normalizer() -> AsyncMock:
    """Fixture for a mock stream normalizer."""
    normalizer = AsyncMock(spec=IStreamNormalizer)
    normalizer.process_stream.return_value = AsyncMock()
    return normalizer


@pytest.fixture
def response_processor(
    mock_response_parser: MagicMock,
    mock_middleware_application_manager: AsyncMock,
    mock_loop_detector: AsyncMock,
    mock_stream_normalizer: AsyncMock,
) -> ResponseProcessor:
    """Fixture for a ResponseProcessor instance with mocked dependencies."""
    # Create a mock middleware for testing
    mock_middleware = MagicMock()
    return ResponseProcessor(
        response_parser=mock_response_parser,
        middleware_application_manager=mock_middleware_application_manager,
        loop_detector=mock_loop_detector,
        stream_normalizer=mock_stream_normalizer,
        middleware_list=[mock_middleware],
    )


@pytest.fixture
def response_processor_no_normalizer(
    mock_response_parser: MagicMock,
    mock_middleware_application_manager: AsyncMock,
    mock_loop_detector: AsyncMock,
) -> ResponseProcessor:
    """Fixture for a ResponseProcessor instance without a stream normalizer."""
    # Create a mock middleware for testing
    mock_middleware = MagicMock()
    return ResponseProcessor(
        response_parser=mock_response_parser,
        middleware_application_manager=mock_middleware_application_manager,
        loop_detector=mock_loop_detector,
        stream_normalizer=None,  # Explicitly pass None
        middleware_list=[mock_middleware],
    )


class TestResponseProcessor:
    """Tests for the ResponseProcessor class."""

    @pytest.mark.asyncio
    async def test_process_response_success(
        self, response_processor: ResponseProcessor, mock_response_parser: MagicMock
    ) -> None:
        """Test successful processing of a non-streaming response."""
        mock_response_parser.parse_response.return_value = {"key": "value"}
        mock_response_parser.extract_content.return_value = "test content"
        mock_response_parser.extract_usage.return_value = {"tokens": 10}
        mock_response_parser.extract_metadata.return_value = {"model": "gpt-3.5"}

        response = {"choices": [{"message": {"content": "hello"}}]}
        processed = await response_processor.process_response(response, "session123")

        assert processed.content == "test content"
        assert processed.usage == {"tokens": 10}
        assert processed.metadata == {"model": "gpt-3.5"}
        mock_response_parser.parse_response.assert_called_once_with(response)

    @pytest.mark.asyncio
    async def test_process_response_loop_detection(
        self, response_processor: ResponseProcessor, mock_loop_detector: AsyncMock
    ) -> None:
        """Test loop detection in a non-streaming response."""
        mock_loop_detector.check_for_loops.return_value = MagicMock(
            has_loop=True, pattern="loop", repetitions=3
        )
        with pytest.raises(LoopDetectionError):
            await response_processor.process_response("loop content loop", "session123")

    @pytest.mark.asyncio
    async def test_process_response_parsing_error(
        self, response_processor: ResponseProcessor, mock_response_parser: MagicMock
    ) -> None:
        """Test parsing error in a non-streaming response."""
        mock_response_parser.parse_response.side_effect = ParsingError("invalid format")
        with pytest.raises(ParsingError):
            await response_processor.process_response("invalid json", "session123")

    @pytest.mark.asyncio
    async def test_process_response_middleware_application(
        self,
        response_processor: ResponseProcessor,
        mock_middleware_application_manager: AsyncMock,
        mock_response_parser: MagicMock,
    ) -> None:
        """Test middleware application for non-streaming responses."""
        original_content = "initial content"
        modified_content = "modified content"
        response = {"choices": [{"message": {"content": original_content}}]}
        mock_response_parser.parse_response.return_value = {}
        mock_response_parser.extract_content.return_value = original_content
        mock_middleware_application_manager.apply_middleware = AsyncMock(
            return_value=modified_content
        )

        processed = await response_processor.process_response(response, "session123")

        mock_middleware_application_manager.apply_middleware.assert_called_once()
        assert processed.content == modified_content

    @pytest.mark.asyncio
    async def test_process_streaming_response_success(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: AsyncMock
    ) -> None:
        """Test successful processing of a streaming response."""

        async def mock_stream_generator() -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(content="chunk1", is_done=False)
            yield StreamingContent(content="chunk2", is_done=True)

        mock_stream_normalizer.process_stream.return_value = mock_stream_generator()

        response_chunks = [
            StreamingChatResponse(content="data1", model="test"),
            StreamingChatResponse(content="data2", model="test"),
        ]

        # Simulate an async iterator from a list of chunks
        async def async_iter_from_list(
            data_list: list[StreamingChatResponse],
        ) -> AsyncGenerator[StreamingChatResponse, None]:
            for item in data_list:
                yield item

        processed_chunks = [
            chunk
            async for chunk in response_processor.process_streaming_response(
                async_iter_from_list(response_chunks), "session123"
            )
        ]

        assert len(processed_chunks) == 2
        assert processed_chunks[0].content == "chunk1"
        assert processed_chunks[1].content == "chunk2"
        mock_stream_normalizer.process_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_streaming_response_error_handling(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: AsyncMock
    ) -> None:
        """Test error handling during streaming response processing."""

        async def error_stream_generator() -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(content="valid", is_done=False)
            raise ValueError("Stream error")

        mock_stream_normalizer.process_stream.return_value = error_stream_generator()

        response_chunks = [StreamingChatResponse(content="data", model="test")]
        processed_chunks = []
        with patch(
            "src.core.services.response_processor_service.logger"
        ) as mock_logger:

            async def async_iter_from_list(
                data_list: list[StreamingChatResponse],
            ) -> AsyncGenerator[StreamingChatResponse, None]:
                for item in data_list:
                    yield item

            async for chunk in response_processor.process_streaming_response(
                async_iter_from_list(response_chunks), "session123"
            ):
                processed_chunks.append(chunk)

            assert len(processed_chunks) == 2
            assert processed_chunks[0].content == "valid"
            assert (
                processed_chunks[1].content is not None
                and "Stream error" in processed_chunks[1].content
            )
            assert processed_chunks[1].metadata.get("error") is True
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_streaming_response_raw_iterator(
        self,
        response_processor_no_normalizer: ResponseProcessor,
        mock_stream_normalizer: AsyncMock,
    ) -> None:
        """Test processing of raw async iterators without stream normalizer."""

        async def raw_chunks() -> AsyncGenerator[StreamingChatResponse, None]:
            yield StreamingChatResponse(content="raw_chunk1", model="test_model")
            yield StreamingChatResponse(content="raw_chunk2", model="test_model")

        processed_responses = [
            p
            async for p in response_processor_no_normalizer.process_streaming_response(
                raw_chunks(), "session_id"
            )
        ]

        assert len(processed_responses) == 2
        assert processed_responses[0].content == "raw_chunk1"
        assert processed_responses[0].metadata["model"] == "test_model"
        assert processed_responses[1].content == "raw_chunk2"
        assert processed_responses[1].metadata["model"] == "test_model"
        mock_stream_normalizer.process_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_streaming_response_raw_dict_chunks(
        self, response_processor_no_normalizer: ResponseProcessor
    ) -> None:
        """Test processing raw dictionary chunks directly."""

        async def dict_chunks() -> AsyncGenerator[dict, None]:
            yield {"choices": [{"delta": {"content": "dict_chunk1"}}]}
            yield {"choices": [{"delta": {"content": "dict_chunk2"}}]}

        processed_responses = [
            p
            async for p in response_processor_no_normalizer.process_streaming_response(
                dict_chunks(), "session_id"
            )
        ]

        assert len(processed_responses) == 2
        assert processed_responses[0].content == "dict_chunk1"
        assert processed_responses[1].content == "dict_chunk2"

    @pytest.mark.asyncio
    async def test_process_streaming_response_raw_bytes_sse_chunks(
        self, response_processor_no_normalizer: ResponseProcessor
    ) -> None:
        """Test processing raw bytes (SSE format) chunks directly."""

        async def bytes_chunks() -> AsyncGenerator[bytes, None]:
            yield b'data: {"choices": [{"delta": {"content": "byte_chunk1"}}]}\n\n'
            yield b'data: {"choices": [{"delta": {"content": "byte_chunk2"}}]}\n\n'

        processed_responses = [
            p
            async for p in response_processor_no_normalizer.process_streaming_response(
                bytes_chunks(), "session_id"
            )
        ]

        assert len(processed_responses) == 2
        assert processed_responses[0].content == "byte_chunk1"
        assert processed_responses[1].content == "byte_chunk2"

    @pytest.mark.asyncio
    async def test_process_streaming_response_raw_unrecognized_chunks(
        self, response_processor_no_normalizer: ResponseProcessor
    ) -> None:
        """Test processing raw unrecognized chunks directly."""

        async def unrecognized_chunks() -> AsyncGenerator[Any, None]:
            yield 123  # An integer
            yield ["list", "chunk"]  # A list

        processed_responses = [
            p
            async for p in response_processor_no_normalizer.process_streaming_response(
                unrecognized_chunks(), "session_id"
            )
        ]

        assert len(processed_responses) == 2
        assert processed_responses[0].content == "123"
        assert processed_responses[1].content == "['list', 'chunk']"
