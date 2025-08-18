"""Tests for the response processor."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatResponse,
)
from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.response_middleware_service import (
    ContentFilterMiddleware,
    LoggingMiddleware,
)
from src.core.services.response_processor_service import ResponseProcessor


class MockLoopDetector(ILoopDetector):
    """Mock loop detector for testing."""

    def __init__(self, should_detect_loop: bool = False) -> None:
        self.should_detect_loop = should_detect_loop
        self.check_called = False
        self.last_content = ""
        self.registered_tool_calls: list[dict[str, Any]] = []
        self.history_cleared = False

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """Check for loops in content."""
        self.check_called = True
        self.last_content = content

        if self.should_detect_loop:
            return LoopDetectionResult(
                has_loop=True,
                pattern="test pattern",
                repetitions=3,
                details={"test": "detail"},
            )
        else:
            return LoopDetectionResult(has_loop=False, modified_content=content)

    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        """Update configuration."""

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """Register a tool call for future loop detection."""
        self.registered_tool_calls.append(
            {"tool_name": tool_name, "arguments": arguments}
        )

    async def clear_history(self) -> None:
        """Clear all recorded history."""
        self.history_cleared = True


class TrackingMiddleware(IResponseMiddleware):
    """Middleware that tracks calls for testing."""

    def __init__(self) -> None:
        self.processed_responses: list[ProcessedResponse] = []
        self.processed_count = 0

    async def process(
        self,
        response: ProcessedResponse,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        """Process a response."""
        self.processed_responses.append(response)
        self.processed_count += 1
        return response


@pytest.fixture
def mock_loop_detector() -> MockLoopDetector:
    """Create a mock loop detector."""
    return MockLoopDetector()


@pytest.fixture
def tracking_middleware() -> TrackingMiddleware:
    """Create a tracking middleware."""
    return TrackingMiddleware()


@pytest.fixture
def response_processor(
    mock_loop_detector: MockLoopDetector, tracking_middleware: TrackingMiddleware
) -> ResponseProcessor:
    """Create a response processor with the mock components."""
    middleware = [
        ContentFilterMiddleware(),
        LoggingMiddleware(),
        tracking_middleware,
    ]
    return ResponseProcessor(mock_loop_detector, middleware)


def test_response_processor_initialization() -> None:
    """Test that response processor initializes correctly."""
    # Create with no middleware or loop detector
    processor = ResponseProcessor()
    assert processor._loop_detector is None
    assert len(processor._middleware) == 0

    # Create with loop detector but no middleware
    loop_detector = MockLoopDetector()
    processor = ResponseProcessor(loop_detector)
    assert processor._loop_detector is loop_detector
    assert len(processor._middleware) == 0

    # Create with middleware but no loop detector
    middleware = [ContentFilterMiddleware(), LoggingMiddleware()]
    processor = ResponseProcessor(None, middleware)
    assert processor._loop_detector is None
    assert len(processor._middleware) == 2

    # Create with both
    processor = ResponseProcessor(loop_detector, middleware)
    assert processor._loop_detector is loop_detector
    assert len(processor._middleware) == 2


@pytest.mark.asyncio
async def test_process_response(
    response_processor: ResponseProcessor,
    tracking_middleware: TrackingMiddleware,
    mock_loop_detector: MockLoopDetector,
) -> None:
    """Test processing a complete response."""
    # Create a sample response
    response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant", content="This is a test response."
                ),
                finish_reason="stop",
            )
        ],
    )

    # Process the response
    result = await response_processor.process_response(response, "test-session")

    # Verify loop detector was called
    assert mock_loop_detector.check_called
    assert mock_loop_detector.last_content == "This is a test response."

    # Verify middleware was called
    assert tracking_middleware.processed_count == 1
    assert (
        tracking_middleware.processed_responses[0].content == "This is a test response."
    )

    # Verify result
    assert result.content == "This is a test response."
    assert result.metadata["id"] == "test-id"
    assert result.metadata["model"] == "test-model"


@pytest.mark.asyncio
async def test_loop_detection(
    mock_loop_detector: MockLoopDetector, tracking_middleware: TrackingMiddleware
) -> None:
    """Test loop detection in response processing."""
    # Configure loop detector to detect loops
    mock_loop_detector.should_detect_loop = True

    # Create processor with the configured detector
    processor = ResponseProcessor(mock_loop_detector, [tracking_middleware])

    # Create a sample response
    response = ChatResponse(
        id="test-id",
        created=1234567890,
        model="test-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content="This is a test response with repetitive content.",
                ),
                finish_reason="stop",
            )
        ],
    )

    # Process the response
    with pytest.raises(Exception) as excinfo:
        # Should raise a loop detection error
        await processor.process_response(response, "test-session")

    # Verify error contains loop information
    assert "loop" in str(excinfo.value).lower()

    # Verify loop detector was called
    assert mock_loop_detector.check_called

    # Check middleware wasn't called after loop detection
    assert tracking_middleware.processed_count == 0


@pytest.mark.asyncio
async def test_streaming_response_processing(
    response_processor: ResponseProcessor, tracking_middleware: TrackingMiddleware
) -> None:
    """Test processing a streaming response."""

    # Create a streaming response iterator
    async def sample_stream() -> AsyncIterator[dict[str, Any]]:
        chunks = [
            {"id": "1", "choices": [{"delta": {"content": "This "}}]},
            {"id": "1", "choices": [{"delta": {"content": "is "}}]},
            {"id": "1", "choices": [{"delta": {"content": "a "}}]},
            {"id": "1", "choices": [{"delta": {"content": "test."}}]},
        ]
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0.01)

    # Process the streaming response
    stream_processor = response_processor.process_streaming_response(
        sample_stream(), "test-session"
    )

    # Collect all processed chunks
    results = []
    async for chunk in stream_processor:
        results.append(chunk)

    # Verify middleware was called for each chunk
    assert tracking_middleware.processed_count == 4

    # Verify all chunks were processed
    assert len(results) == 4
    assert results[0].content == "This "
    assert results[1].content == "is "
    assert results[2].content == "a "
    assert results[3].content == "test."


@pytest.mark.asyncio
async def test_middleware_registration() -> None:
    """Test registering middleware components."""
    processor = ResponseProcessor()
    middleware = TrackingMiddleware()
    await processor.register_middleware(middleware)
    assert len(processor._middleware) == 1
    middleware2 = TrackingMiddleware()
    await processor.register_middleware(middleware2, priority=10)
    assert len(processor._middleware) == 2
