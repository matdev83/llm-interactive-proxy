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
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)


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
def mock_loop_detector() -> AsyncMock:
    """Fixture for a mock loop detector."""
    detector = AsyncMock(spec=ILoopDetector)
    detector.check_for_loops.return_value = MagicMock(has_loop=False)
    return detector


@pytest.fixture
def mock_stream_normalizer() -> MagicMock:
    """Fixture for a mock stream normalizer.

    Note: After unified pipeline refactoring, ResponseProcessor uses the stream
    normalizer for both streaming and non-streaming responses. Non-streaming
    responses are wrapped as single-chunk streams.
    """
    normalizer = MagicMock(spec=IStreamNormalizer)

    # Create an async generator that yields StreamingContent
    async def _default_process_stream(
        *args: Any, **kwargs: Any
    ) -> AsyncGenerator[StreamingContent, None]:
        yield StreamingContent(
            content="default content",
            is_done=True,
            metadata={},
        )

    normalizer.process_stream = MagicMock(side_effect=_default_process_stream)
    normalizer.reset = MagicMock()
    return normalizer


@pytest.fixture
def response_processor(
    mock_response_parser: MagicMock,
    mock_loop_detector: AsyncMock,
    mock_stream_normalizer: MagicMock,
) -> ResponseProcessor:
    """Fixture for a ResponseProcessor instance with mocked dependencies.

    Note: After unified pipeline refactoring, ResponseProcessor no longer needs
    a separate middleware_application_manager. All middleware is applied through
    the streaming pipeline.
    """
    # Create a mock middleware for testing
    mock_middleware = MagicMock()
    return ResponseProcessor(
        response_parser=mock_response_parser,
        loop_detector=mock_loop_detector,
        stream_normalizer=mock_stream_normalizer,
        middleware_list=[mock_middleware],
    )


class TestResponseProcessor:
    """Tests for the ResponseProcessor class."""

    def test_initializes_stream_normalizer_when_processors_supplied(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Ensure specialized processors trigger default StreamNormalizer creation."""

        tool_call_processor = MagicMock()

        with patch(
            "src.core.services.response_processor_service.StreamNormalizer"
        ) as mock_normalizer:
            ResponseProcessor(
                response_parser=mock_response_parser,
                loop_detector=mock_loop_detector,
                stream_normalizer=None,
                tool_call_repair_processor=tool_call_processor,
                middleware_list=[MagicMock()],
            )

        mock_normalizer.assert_called_once()
        processors_arg = mock_normalizer.call_args[0][0]
        assert processors_arg[0] is tool_call_processor
        assert any(
            isinstance(processor, ContentAccumulationProcessor)
            for processor in processors_arg[1:]
        )

    def test_requires_stream_normalizer_without_processors(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Streaming pipeline must be explicitly configured."""

        with pytest.raises(RuntimeError):
            ResponseProcessor(
                response_parser=mock_response_parser,
                loop_detector=mock_loop_detector,
                stream_normalizer=None,
                middleware_list=[MagicMock()],
            )

    @pytest.mark.asyncio
    async def test_process_response_success(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Test successful processing of a non-streaming response through unified pipeline."""
        mock_response_parser.parse_response.return_value = {"key": "value"}
        mock_response_parser.extract_content.return_value = "test content"
        mock_response_parser.extract_usage.return_value = {"tokens": 10}
        mock_response_parser.extract_metadata.return_value = {"model": "gpt-3.5"}

        # Create a normalizer that returns the parsed content
        async def _process_stream(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(
                content="test content",
                is_done=True,
                metadata={"model": "gpt-3.5"},
                usage={"tokens": 10},
            )

        mock_normalizer = MagicMock(spec=IStreamNormalizer)
        mock_normalizer.process_stream = MagicMock(side_effect=_process_stream)
        mock_normalizer.reset = MagicMock()

        processor = ResponseProcessor(
            response_parser=mock_response_parser,
            loop_detector=mock_loop_detector,
            stream_normalizer=mock_normalizer,
        )

        response = {"choices": [{"message": {"content": "hello"}}]}
        processed = await processor.process_response(response, "session123")

        # The content comes from the stream normalizer output
        assert processed.content == "test content"
        assert processed.usage == {"tokens": 10}
        assert "model" in processed.metadata
        mock_response_parser.parse_response.assert_called_once_with(response)

    @pytest.mark.asyncio
    async def test_process_response_loop_detection(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Test loop detection in a non-streaming response via pipeline metadata."""
        mock_response_parser.parse_response.return_value = {}
        mock_response_parser.extract_content.return_value = "loop content"
        mock_response_parser.extract_usage.return_value = None
        mock_response_parser.extract_metadata.return_value = {}

        # Create a normalizer that returns content with loop_detected flag
        async def _process_stream(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(
                content="loop content",
                is_done=True,
                metadata={"loop_detected": True, "pattern": "loop"},
            )

        mock_normalizer = MagicMock(spec=IStreamNormalizer)
        mock_normalizer.process_stream = MagicMock(side_effect=_process_stream)
        mock_normalizer.reset = MagicMock()

        processor = ResponseProcessor(
            response_parser=mock_response_parser,
            loop_detector=mock_loop_detector,
            stream_normalizer=mock_normalizer,
        )

        with pytest.raises(LoopDetectionError):
            await processor.process_response("loop content loop", "session123")

    @pytest.mark.asyncio
    async def test_process_response_parsing_error(
        self, response_processor: ResponseProcessor, mock_response_parser: MagicMock
    ) -> None:
        """Test parsing error in a non-streaming response."""
        mock_response_parser.parse_response.side_effect = ParsingError("invalid format")
        with pytest.raises(ParsingError):
            await response_processor.process_response("invalid json", "session123")

    @pytest.mark.asyncio
    async def test_process_response_unified_pipeline(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Test that non-streaming responses flow through the unified pipeline.

        After refactoring, both streaming and non-streaming responses
        use the same processor chain (stream normalizer).
        """
        original_content = "initial content"
        modified_content = "modified content"

        mock_response_parser.parse_response.return_value = {}
        mock_response_parser.extract_content.return_value = original_content
        mock_response_parser.extract_usage.return_value = None
        mock_response_parser.extract_metadata.return_value = {}

        # Create a normalizer that simulates middleware modification
        async def _process_stream(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(
                content=modified_content,  # Middleware "modified" the content
                is_done=True,
                metadata={"processed_by_pipeline": True},
            )

        mock_normalizer = MagicMock(spec=IStreamNormalizer)
        mock_normalizer.process_stream = MagicMock(side_effect=_process_stream)
        mock_normalizer.reset = MagicMock()

        processor = ResponseProcessor(
            response_parser=mock_response_parser,
            loop_detector=mock_loop_detector,
            stream_normalizer=mock_normalizer,
        )

        response = {"choices": [{"message": {"content": original_content}}]}
        processed = await processor.process_response(response, "session123")

        # The content should be what the pipeline returned
        assert processed.content == modified_content
        mock_normalizer.process_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_streaming_response_success(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: MagicMock
    ) -> None:
        """Test successful processing of a streaming response."""

        async def mock_stream_generator(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(content="chunk1", is_done=False)
            yield StreamingContent(content="chunk2", is_done=True)

        mock_stream_normalizer.process_stream = MagicMock(
            side_effect=mock_stream_generator
        )

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
        assert processed_chunks[0].metadata["session_id"] == "session123"
        assert processed_chunks[1].metadata["session_id"] == "session123"

    @pytest.mark.asyncio
    async def test_process_streaming_response_resets_normalizer(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: MagicMock
    ) -> None:
        """Ensure the stream normalizer state is reset before each stream."""

        async def mock_stream_generator(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            if False:  # pragma: no cover - generator requires a yield
                yield StreamingContent(content="", is_done=True)

        mock_stream_normalizer.process_stream = MagicMock(
            side_effect=mock_stream_generator
        )

        async def empty_request_stream() -> AsyncGenerator[StreamingChatResponse, None]:
            if False:  # pragma: no cover - generator requires a yield
                yield StreamingChatResponse(content="", model="test")

        _ = [
            chunk
            async for chunk in response_processor.process_streaming_response(
                empty_request_stream(),
                "session123",
            )
        ]

        # Unified pipeline resets before streaming
        mock_stream_normalizer.reset.assert_called()

    @pytest.mark.asyncio
    async def test_process_streaming_response_error_handling(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: MagicMock
    ) -> None:
        """Test error handling during streaming response processing."""

        async def error_stream_generator(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(content="valid", is_done=False)
            raise ValueError("Stream error")

        mock_stream_normalizer.process_stream = MagicMock(
            side_effect=error_stream_generator
        )

        response_chunks = [StreamingChatResponse(content="data", model="test")]
        processed_chunks = []
        with patch("src.core.services.response_processor_service.logger"):

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

    @pytest.mark.asyncio
    async def test_process_streaming_response_delegates_to_normalizer(
        self, response_processor: ResponseProcessor, mock_stream_normalizer: MagicMock
    ) -> None:
        """Verify that the streaming response delegates to the stream normalizer."""

        async def mock_stream_generator(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(
                content="normalized",
                is_done=True,
                metadata={"normalized": True},
            )

        mock_stream_normalizer.process_stream = MagicMock(
            side_effect=mock_stream_generator
        )

        async def single_chunk_stream() -> AsyncGenerator[StreamingChatResponse, None]:
            yield StreamingChatResponse(content="raw", model="test-model")

        chunks = [
            chunk
            async for chunk in response_processor.process_streaming_response(
                single_chunk_stream(), "session456"
            )
        ]

        assert len(chunks) == 1
        assert chunks[0].content == "normalized"
        assert chunks[0].metadata.get("normalized") is True

    def test_streaming_reset_prevents_content_leak_between_requests(
        self,
        mock_response_parser: MagicMock,
        mock_loop_detector: AsyncMock,
    ) -> None:
        """Verify that the stream normalizer is reset between requests to prevent leaks."""
        mock_normalizer = MagicMock(spec=IStreamNormalizer)

        async def _process_stream(
            *args: Any, **kwargs: Any
        ) -> AsyncGenerator[StreamingContent, None]:
            yield StreamingContent(content="content", is_done=True)

        mock_normalizer.process_stream = MagicMock(side_effect=_process_stream)
        mock_normalizer.reset = MagicMock()

        processor = ResponseProcessor(
            response_parser=mock_response_parser,
            loop_detector=mock_loop_detector,
            stream_normalizer=mock_normalizer,
        )

        # The processor should have a unified pipeline that resets the normalizer
        assert processor._unified_pipeline is not None
        assert processor._stream_normalizer is mock_normalizer
