import pytest
from src.loop_detection.detector import LoopDetectionConfig, LoopDetector
from src.loop_detection.streaming import wrap_streaming_content_with_loop_detection


@pytest.mark.asyncio
async def test_stream_cancellation_on_loop() -> None:
    """Ensure the streaming wrapper cancels output when a loop is detected."""

    # Configure detector with VERY low thresholds so the test is fast
    config = LoopDetectionConfig(
        buffer_size=1024,
        max_pattern_length=8192,
    )
    # Three repetitions of a 1-char pattern should be enough
    config.short_pattern_threshold.min_repetitions = 3
    config.short_pattern_threshold.min_total_length = 3
    detector = LoopDetector(config=config)

    async def fake_stream() -> str:
        # Emit a short normal prefix
        yield "Hello, world!\n"
        # Then emit a 120-char block repeated to form a loop
        yield ("ERROR " * 20) * 3
        # This line should never be reached - wrapper should stop before
        yield "Should not reach here"

    collected = []
    async for chunk in wrap_streaming_content_with_loop_detection(
        fake_stream(), detector
    ):
        collected.append(chunk)
        # Break if we see the cancellation notice for safety
        if "Response cancelled" in chunk:
            break

    joined = "".join(collected)
    assert "Response cancelled" in joined, "Cancellation message not injected"
    assert "Should not reach here" not in joined, "Wrapper failed to stop the stream"
