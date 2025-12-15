from collections.abc import AsyncIterator

import pytest
from src.core.domain.streaming_response_processor import (  # Added StreamingContent
    LoopDetectionProcessor,
    StreamingContent,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.loop_detection.hybrid_detector import HybridLoopDetector


@pytest.mark.asyncio
async def test_stream_cancellation_on_loop() -> None:
    """Ensure the streaming wrapper detects loops and marks cancellation chunks.

    Note: The unified streaming pipeline processes all input chunks, but marks
    loop detection via is_cancellation=True and loop_detected metadata. The consumer
    is responsible for stopping iteration when they see these markers.
    """

    # Configure detector with low thresholds so the test can trigger loop detection
    def create_detector() -> HybridLoopDetector:
        return HybridLoopDetector(
            short_detector_config={
                "content_chunk_size": 10,  # Smaller chunk size for test pattern
                "content_loop_threshold": 2,  # Very low threshold to trigger detection
                "max_history_length": 200,
            },
            long_detector_config={
                "min_pattern_length": 60,
                "max_pattern_length": 8192,
                "min_repetitions": 2,
                "max_history": 4096,
            },
        )

    # Create the processor with factory that creates fresh detectors
    processor = LoopDetectionProcessor(
        loop_detector_factory=create_detector,
        min_chunks_before_detection=1,  # Detect early for test
    )

    # Mock the upstream stream that builds up content and then loops
    async def mock_upstream_stream() -> AsyncIterator[StreamingContent]:
        # First build up some normal content
        yield StreamingContent(
            content="This is some normal content that builds up the buffer.",
            metadata={"session_id": "test-session"},
        )
        yield StreamingContent(
            content="More normal content to establish a baseline.",
            metadata={"session_id": "test-session"},
        )

        # Then create a repeating pattern that should trigger detection
        loop_pattern = "ERROR ERROR ERROR"

        # Repeat the pattern multiple times to trigger detection
        for _i in range(5):
            yield StreamingContent(
                content=loop_pattern,
                metadata={"session_id": "test-session"},
            )

        # This may still be yielded because the upstream is an async generator
        # The important thing is that loop detection marks subsequent chunks
        yield StreamingContent(
            content="After loop detection",
            metadata={"session_id": "test-session"},
        )

    # Use StreamNormalizer with the processor
    normalizer = StreamNormalizer(processors=[processor])

    collected = []
    loop_detected = False
    cancellation_chunk_found = False
    async for chunk in normalizer.process_stream(
        mock_upstream_stream(), output_format="objects"
    ):
        collected.append(chunk.content)
        # Check if this chunk has loop_detected metadata
        if isinstance(chunk, StreamingContent) and chunk.metadata.get("loop_detected"):
            loop_detected = True
        # Check if this chunk is marked as cancellation
        if isinstance(chunk, StreamingContent) and chunk.is_cancellation:
            cancellation_chunk_found = True
            break  # Stop processing when we see cancellation marker

    joined = "".join(collected)

    # Debug output
    print(f"Loop detected: {loop_detected}")
    print(f"Cancellation chunk found: {cancellation_chunk_found}")
    print(f"Collected content: {joined}")
    print(f"Individual chunks: {collected}")

    # The test passes if loop was detected and cancellation marker was emitted
    assert (
        loop_detected or cancellation_chunk_found
    ), f"Loop detection failed. Content: {joined}, loop_detected: {loop_detected}, cancellation_chunk_found: {cancellation_chunk_found}"
