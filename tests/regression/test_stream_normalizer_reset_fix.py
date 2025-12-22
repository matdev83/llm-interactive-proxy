"""
Regression tests for StreamNormalizer concurrency issues.

Ensures that StreamNormalizer (which is a Singleton) does not call reset() on its
processors during request processing, as this would wipe state for all concurrent streams.
"""

import pytest
from src.core.ports.streaming_contracts import IStreamProcessor, StreamingContent
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class MockStatefulProcessor(IStreamProcessor):
    def __init__(self):
        self.reset_called = False
        self.process_called = False

    async def process(self, content: StreamingContent) -> StreamingContent:
        self.process_called = True
        return content

    def reset(self) -> None:
        self.reset_called = True


@pytest.mark.asyncio
async def test_stream_normalizer_does_not_reset_processors_on_process():
    """
    Regression test for Concurrency Global Wipe.

    Verifies that StreamNormalizer.process_stream() does NOT call reset() on its processors.
    Since StreamNormalizer is registered as a Singleton, calling reset() globally wipes
    state for all concurrent requests sharing the processor (e.g. StreamingContextRegistry).
    """
    # Arrange
    mock_processor = MockStatefulProcessor()
    normalizer = StreamNormalizer(processors=[mock_processor])

    # Mock stream input
    async def mock_stream():
        yield StreamingContent(content="test chunk", metadata={"stream_id": "test-1"})

    # Act
    # Consume the generator to trigger processing
    async for _ in normalizer.process_stream(mock_stream()):
        pass

    # Assert
    assert mock_processor.process_called, "Processor.process() should have been called"
    assert not mock_processor.reset_called, (
        "Processor.reset() must NOT be called by StreamNormalizer.process_stream(). "
        "StreamNormalizer is a Singleton; calling reset() wipes state for all concurrent streams."
    )
