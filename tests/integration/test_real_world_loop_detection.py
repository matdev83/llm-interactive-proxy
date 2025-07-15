"""
Real-world loop detection tests using actual examples.

These tests use real-world examples of loops and non-loops to verify
that the loop detection system works correctly with realistic content.
"""

import asyncio
from pathlib import Path

import pytest

from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetector
from src.loop_detection.streaming import wrap_streaming_content_with_loop_detection


class TestRealWorldLoopDetection:
    """Test loop detection with real-world examples."""

    def setup_method(self):
        """Set up test configuration with 100 char minimum."""
        self.config = LoopDetectionConfig(
            enabled=True,
            buffer_size=8192,  # Larger buffer for real-world content
            max_pattern_length=2000  # Allow longer patterns for real-world loops
        )
        # Verify our 100 char minimum is set
        assert self.config.short_pattern_threshold.min_total_length == 100
        assert self.config.medium_pattern_threshold.min_total_length == 100
        assert self.config.long_pattern_threshold.min_total_length == 100

    def load_test_data(self, filename: str) -> str:
        """Load test data from file."""
        test_data_path = Path("tests/loop_test_data") / filename
        with open(test_data_path, encoding='utf-8') as f:
            return f.read()

    def test_example1_kiro_loop_detection(self):
        """Test detection of Kiro documentation loop (example1.md)."""
        content = self.load_test_data("example1.md")
        
        detector = LoopDetector(config=self.config)
        
        # Process the content
        result = detector.process_chunk(content)
        
        # Should detect the repeating pattern
        assert result is not None, "Should detect loop in Kiro documentation"
        
        # Verify the detected pattern
        assert result.repetition_count >= 3, f"Should have multiple repetitions, got {result.repetition_count}"
        assert result.total_length >= 100, f"Should meet 100 char minimum, got {result.total_length}"
        
        # The pattern should contain the repeating text about Kiro
        pattern_lower = result.pattern.lower()
        assert any(keyword in pattern_lower for keyword in [
            "kiro", "public preview", "kiro.dev", "official website"
        ]), f"Pattern should contain Kiro-related keywords, got: {result.pattern[:100]}..."
        
        print(f"Detected loop: {result.repetition_count} repetitions of {len(result.pattern)} chars")
        print(f"   Pattern preview: {result.pattern[:100]}...")

    def test_example2_platinum_futures_loop_detection(self):
        """Test detection of CME Platinum Futures loop (example2.md)."""
        content = self.load_test_data("example2.md")
        
        detector = LoopDetector(config=self.config)
        
        # Process the content
        result = detector.process_chunk(content)
        
        # Should detect the repeating pattern
        assert result is not None, "Should detect loop in Platinum Futures documentation"
        
        # Verify the detected pattern
        assert result.repetition_count >= 2, f"Should have multiple repetitions, got {result.repetition_count}"
        assert result.total_length >= 100, f"Should meet 100 char minimum, got {result.total_length}"
        
        # The pattern should contain the repeating text about CME Platinum
        pattern_lower = result.pattern.lower()
        assert any(keyword in pattern_lower for keyword in [
            "cme platinum futures", "ticker symbol", "nymex", "standardized contracts"
        ]), f"Pattern should contain CME-related keywords, got: {result.pattern[:100]}..."
        
        print(f"Detected loop: {result.repetition_count} repetitions of {len(result.pattern)} chars")
        print(f"   Pattern preview: {result.pattern[:100]}...")

    def test_example3_no_loop_false_positive_check(self):
        """Test that no loop is detected in normal content (example3_no_loop.md)."""
        content = self.load_test_data("example3_no_loop.md")
        
        detector = LoopDetector(config=self.config)
        
        # Process the content
        result = detector.process_chunk(content)
        
        # Should NOT detect any loops
        assert result is None, f"Should not detect loop in normal content, but got: {result}"
        
        print("No false positive: Normal content correctly identified as non-looping")

    @pytest.mark.asyncio
    async def test_streaming_loop_detection_example1(self):
        """Test streaming loop detection with example1 content."""
        content = self.load_test_data("example1.md")
        
        detector = LoopDetector(config=self.config)
        
        # Simulate streaming by breaking content into chunks
        chunk_size = 200
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
        
        async def mock_stream():
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0.01)  # Simulate streaming delay
        
        # Wrap with loop detection
        wrapped_stream = wrap_streaming_content_with_loop_detection(mock_stream(), detector)
        
        # Collect chunks until cancellation or completion
        collected_chunks = []
        cancellation_detected = False
        
        async for chunk in wrapped_stream:
            collected_chunks.append(chunk)
            if "Response cancelled" in chunk and "Loop detected" in chunk:
                cancellation_detected = True
                break
        
        # Should have detected and cancelled the stream
        assert cancellation_detected, "Stream should have been cancelled due to loop detection"
        
        full_content = "".join(collected_chunks)
        assert "Loop detected" in full_content, "Cancellation message should mention loop detection"
        
        print("Streaming cancellation worked correctly")

    @pytest.mark.asyncio
    async def test_streaming_no_false_positive_example3(self):
        """Test streaming with normal content doesn't get cancelled."""
        content = self.load_test_data("example3_no_loop.md")
        
        detector = LoopDetector(config=self.config)
        
        # Simulate streaming
        chunk_size = 150
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
        
        async def mock_stream():
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0.01)
        
        # Wrap with loop detection
        wrapped_stream = wrap_streaming_content_with_loop_detection(mock_stream(), detector)
        
        # Collect all chunks
        collected_chunks = []
        async for chunk in wrapped_stream:
            collected_chunks.append(chunk)
            # Break if we see unexpected cancellation
            if "Response cancelled" in chunk:
                break
        
        full_content = "".join(collected_chunks)
        
        # Should NOT have been cancelled
        assert "Response cancelled" not in full_content, "Normal content should not be cancelled"
        assert "Loop detected" not in full_content, "Should not detect loops in normal content"
        
        # Should have received all the content
        assert len(full_content) >= len(content) * 0.9, "Should receive most/all of the original content"
        
        print("Normal streaming completed without false positive")

    def test_unicode_character_counting(self):
        """Test that unicode characters are counted correctly."""
        # Create content with unicode characters
        unicode_content = "🔄 Processing... " * 20  # Each emoji + text is about 16 chars
        
        detector = LoopDetector(config=self.config)
        result = detector.process_chunk(unicode_content)
        
        if result:
            # Verify unicode length calculation
            pattern_unicode_length = len(result.pattern)  # This counts unicode chars correctly
            pattern_byte_length = len(result.pattern.encode('utf-8'))  # This would be different
            
            print(f"Unicode pattern length: {pattern_unicode_length} chars")
            print(f"Byte length: {pattern_byte_length} bytes")
            print(f"Total length: {result.total_length} unicode chars")
            
            # Should meet our 100 unicode char minimum
            assert result.total_length >= 100, f"Should meet 100 unicode char minimum, got {result.total_length}"
        
        print("Unicode character counting works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])