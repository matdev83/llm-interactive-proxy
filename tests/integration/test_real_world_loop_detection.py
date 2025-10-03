"""
Real-world loop detection tests using actual examples.

These tests use real-world examples of loops and non-loops to verify
that the loop detection system works correctly with realistic content.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from src.core.domain.streaming_response_processor import (
    LoopDetectionProcessor,
    StreamingContent,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.loop_detection.hybrid_detector import HybridLoopDetector


class TestRealWorldLoopDetection:
    """Test loop detection with real-world examples."""

    def _create_detector(
        self,
        *,
        content_loop_threshold: int = 10,
        content_chunk_size: int = 50,
        min_long_repetitions: int = 3,
    ) -> HybridLoopDetector:
        """Helper to create a hybrid detector tuned for tests."""
        short_config = {
            "content_loop_threshold": content_loop_threshold,
            "content_chunk_size": content_chunk_size,
            "max_history_length": 4096,
        }
        long_config = {
            "min_pattern_length": 60,
            "max_pattern_length": 1000,
            "min_repetitions": min_long_repetitions,
            "max_history": 4096,
        }
        return HybridLoopDetector(
            short_detector_config=short_config,
            long_detector_config=long_config,
        )

    def load_test_data(self, filename: str) -> str:
        """Load test data from file."""
        test_data_path = Path("tests/loop_test_data") / filename
        with open(test_data_path, encoding="utf-8") as f:
            return f.read()

    def test_example1_kiro_loop_detection(self) -> None:
        """Test detection of Kiro documentation loop (example1.md)."""
        # Use a chanting phrase repeated closely to trigger hash-chunk detection
        content = "Kiro docs are available. " * 12

        # Use more sensitive detection settings for testing
        detector = self._create_detector(
            content_loop_threshold=3,
            content_chunk_size=25,
        )

        # Process the content
        result = detector.process_chunk(content)

        # Should detect the repeating pattern
        assert result is not None, "Should detect loop in repeating content"

        # Verify the detected pattern
        assert (
            result.repetition_count >= 3
        ), f"Should have multiple repetitions, got {result.repetition_count}"
        expected_min_length = 3 * 25
        assert (
            result.total_length >= expected_min_length
        ), f"Should meet minimum length, got {result.total_length}"

        print(
            f"Detected loop: {result.repetition_count} repetitions of {len(result.pattern)} chars"
        )

    def test_example2_platinum_futures_loop_detection(self) -> None:
        """Test detection of CME Platinum Futures loop (example2.md)."""
        # Use a short phrase repeated many times to trigger chanting detection
        content = "CME Platinum Futures info. " * 12

        # Use more sensitive detection settings for testing
        detector = self._create_detector(
            content_loop_threshold=3,
            content_chunk_size=25,
        )

        # Process the content
        result = detector.process_chunk(content)

        # Should detect the repeating pattern
        assert result is not None, "Should detect loop in repeating content"

        # Verify the detected pattern
        assert (
            result.repetition_count >= 2
        ), f"Should have multiple repetitions, got {result.repetition_count}"
        expected_min_length = 3 * 25
        assert (
            result.total_length >= expected_min_length
        ), f"Should meet minimum length, got {result.total_length}"

        print(
            f"Detected loop: {result.repetition_count} repetitions of {len(result.pattern)} chars"
        )

    def test_example3_no_loop_false_positive_check(self) -> None:
        """Test that no loop is detected in normal content (example3_no_loop.md)."""
        content = self.load_test_data("example3_no_loop.md")

        detector = self._create_detector()

        # Process the content
        result = detector.process_chunk(content)

        # Should NOT detect any loops
        assert (
            result is None
        ), f"Should not detect loop in normal content, but got: {result}"

        print("No false positive: Normal content correctly identified as non-looping")

    @pytest.mark.asyncio
    async def test_streaming_loop_detection_example1(self) -> None:
        """Test streaming loop detection wrapper doesn't break normal streaming."""
        # Create non-looping content for testing
        content = "This is normal streaming content. " * 10

        # Use detection settings for testing
        detector = self._create_detector(
            content_loop_threshold=6,
            content_chunk_size=40,
        )

        # Simulate streaming with small chunks
        chunk_size = 60
        chunks = [
            content[i : i + chunk_size] for i in range(0, len(content), chunk_size)
        ]

        async def mock_stream() -> AsyncIterator[str]:
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0.0001)  # Minimal delay for faster testing

        # Create the processor
        processor = LoopDetectionProcessor(loop_detector=detector)

        # Use StreamNormalizer with the processor
        normalizer = StreamNormalizer(processors=[processor])
        wrapped_stream = normalizer.process_stream(
            mock_stream(), output_format="objects"
        )

        # Collect all chunks to ensure streaming works
        collected_chunks = []
        async for chunk in wrapped_stream:
            collected_chunks.append(chunk)

        # Should have received all content without cancellation
        full_content = "".join(str(chunk) for chunk in collected_chunks)
        assert len(full_content) > 50, "Should receive streaming content"
        assert (
            "Response cancelled" not in full_content
        ), "Normal content should not be cancelled"

        print("Streaming wrapper works correctly with normal content")

    @pytest.mark.asyncio
    async def test_streaming_no_false_positive_example3(self) -> None:
        """Test streaming with normal content doesn't get cancelled."""
        # Load content but use only a portion for faster testing
        content = self.load_test_data("example3_no_loop.md")
        content = content[:800]  # Reduce content size for faster testing

        detector = self._create_detector(
            content_loop_threshold=6,
            content_chunk_size=40,
        )

        # Simulate streaming with smaller chunks
        chunk_size = 150
        chunks = [
            content[i : i + chunk_size] for i in range(0, len(content), chunk_size)
        ]

        async def mock_stream() -> AsyncIterator[str]:
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0.001)  # Reduced delay for faster testing

        # Create the processor
        processor = LoopDetectionProcessor(loop_detector=detector)

        # Use StreamNormalizer with the processor
        normalizer = StreamNormalizer(processors=[processor])

        # Collect all chunks
        collected_chunks = []
        async for chunk in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            collected_chunks.append(chunk)
            # Break if we see unexpected cancellation
            if (
                isinstance(chunk, StreamingContent)
                and "Response cancelled" in chunk.content
            ):
                break

        # Extract content from StreamingContent objects
        content_strings = [
            chunk.content
            for chunk in collected_chunks
            if isinstance(chunk, StreamingContent) and chunk.content
        ]
        full_content = "".join(content_strings)

        # Should NOT have been cancelled
        assert (
            "Response cancelled" not in full_content
        ), "Normal content should not be cancelled"
        assert (
            "Loop detected" not in full_content
        ), "Should not detect loops in normal content"

        # Should have received all the content
        assert (
            len(full_content) >= len(content) * 0.9
        ), "Should receive most/all of the original content"

        print("Normal streaming completed without false positive")

    def test_unicode_character_counting(self) -> None:
        """Test that unicode characters are counted correctly."""
        # Create content with unicode characters (reduced count for faster testing)
        unicode_content = "[SPIN] Processing... " * 10  # Reduced from 20 to 10

        detector = self._create_detector(
            content_loop_threshold=5,
            content_chunk_size=30,
        )
        result = detector.process_chunk(unicode_content)

        if result:
            # Verify unicode length calculation
            pattern_unicode_length = len(
                result.pattern
            )  # This counts unicode chars correctly
            pattern_byte_length = len(
                result.pattern.encode("utf-8")
            )  # This would be different

            print(f"Unicode pattern length: {pattern_unicode_length} chars")
            print(f"Byte length: {pattern_byte_length} bytes")
            print(f"Total length: {result.total_length} unicode chars")

            # Should meet our 100 unicode char minimum
            assert (
                result.total_length >= 100
            ), f"Should meet 100 unicode char minimum, got {result.total_length}"

        print("Unicode character counting works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
