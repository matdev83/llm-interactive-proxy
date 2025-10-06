"""
Unit tests for the main LoopDetector class.
"""

import pytest
from src.loop_detection.config import InternalLoopDetectionConfig
from src.loop_detection.detector import LoopDetectionEvent, LoopDetector


class TestLoopDetector:
    """Test the LoopDetector class."""

    def test_detector_initialization(self) -> None:
        """Test that detector initializes correctly."""
        config = InternalLoopDetectionConfig(enabled=True, buffer_size=1024)
        detector = LoopDetector(config=config)

        assert detector.is_enabled() == True
        assert detector.config.buffer_size == 1024

    def test_detector_disabled(self) -> None:
        """Test that disabled detector doesn't process chunks."""
        config = InternalLoopDetectionConfig(enabled=False)
        detector = LoopDetector(config=config)

        # Should not process when disabled
        result = detector.process_chunk("test test test test test")
        assert result is None

    def test_simple_loop_detection_with_chunking(self) -> None:
        """Test detection of simple loops with chunked processing."""
        config = InternalLoopDetectionConfig(
            enabled=True,
            buffer_size=1024,
            content_chunk_size=10,
            content_loop_threshold=3,
        )
        events = []

        def on_loop_detected(event: LoopDetectionEvent) -> None:
            events.append(event)

        detector = LoopDetector(config=config, on_loop_detected=on_loop_detected)

        pattern = "repeatthis"  # 10 chars, matching chunk size
        result = None

        # Process the pattern enough times to trigger the loop
        for i in range(config.content_loop_threshold):
            result = detector.process_chunk(pattern)
            # The loop should be detected on the last chunk
            if i < config.content_loop_threshold - 1:
                assert result is None, f"Loop detected prematurely on iteration {i}"
                assert not events

        # The final chunk should trigger the detection
        assert result is not None, "Loop not detected on the final chunk"
        assert len(events) == 1, "on_loop_detected callback was not triggered"

        # Verify the event details
        event = events[0]
        assert isinstance(event, LoopDetectionEvent)
        assert event.pattern == pattern
        assert event.repetition_count == config.content_loop_threshold

    def test_whitelist_prevents_noise_detection(self) -> None:
        """Detector should ignore loops made of whitelisted noise tokens."""
        config = InternalLoopDetectionConfig(
            enabled=True,
            content_chunk_size=3,
            content_loop_threshold=3,
            whitelist=["---"],
        )
        detector = LoopDetector(config=config)

        # Process a whitelisted pattern repeatedly; it should never trigger detection.
        for _ in range(config.content_loop_threshold + 1):
            event = detector.process_chunk("---")
            assert event is None

        # Reset and ensure a non-whitelisted pattern still triggers detection.
        detector.reset()
        for idx in range(config.content_loop_threshold):
            event = detector.process_chunk("abc")
            if idx < config.content_loop_threshold - 1:
                assert event is None

        assert event is not None

    def test_no_false_positive_normal_text(self) -> None:
        """Test that normal text doesn't trigger false positives."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)

        # Normal text that shouldn't trigger detection
        normal_text = """
        This is a normal response from an AI assistant. 
        It contains various sentences with different content.
        There are no repetitive patterns here that would indicate a loop.
        The text flows naturally from one topic to another.
        """

        result = detector.process_chunk(normal_text)
        assert result is None

    def test_detector_reset(self) -> None:
        """Test that detector reset works correctly."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)

        # Process some text
        detector.process_chunk("Some text to fill the buffer")

        # Check that buffer has content
        assert detector.buffer.size() > 0

        # Reset detector
        detector.reset()

        # Buffer should be empty
        assert detector.buffer.size() == 0
        assert detector.total_processed == 0

    def test_detector_enable_disable(self) -> None:
        """Test enabling and disabling the detector."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)

        assert detector.is_enabled() == True

        detector.disable()
        assert detector.is_enabled() == False

        detector.enable()
        assert detector.is_enabled() == True

    def test_detector_stats(self) -> None:
        """Test that detector statistics are correct."""
        config = InternalLoopDetectionConfig(enabled=True, buffer_size=512)
        detector = LoopDetector(config=config)

        stats = detector.get_stats()

        assert stats["is_active"] == True
        # Note: total_processed and buffer_size are not directly in stats dict
        # They're tracked separately in the detector
        assert stats["config"]["buffer_size"] == 512

    def test_minimum_content_threshold(self) -> None:
        """Test that detector requires minimum content before analyzing."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)

        # Very short text should not trigger analysis
        result = detector.process_chunk("a")
        assert result is None

        result = detector.process_chunk("ab")
        assert result is None

    def test_config_validation(self) -> None:
        """Test that invalid configurations are rejected."""
        # Invalid buffer size
        with pytest.raises(ValueError):
            config = InternalLoopDetectionConfig(enabled=True, buffer_size=-1)
            LoopDetector(config=config)

        # Invalid max pattern length
        with pytest.raises(ValueError):
            config = InternalLoopDetectionConfig(enabled=True, max_pattern_length=0)
            LoopDetector(config=config)

        with pytest.raises(ValueError):
            config = InternalLoopDetectionConfig(enabled=True, content_chunk_size=0)
            LoopDetector(config=config)

        with pytest.raises(ValueError):
            config = InternalLoopDetectionConfig(enabled=True, content_loop_threshold=0)
            LoopDetector(config=config)

        with pytest.raises(ValueError):
            config = InternalLoopDetectionConfig(enabled=True, max_history_length=0)
            LoopDetector(config=config)

    @pytest.mark.asyncio
    async def test_check_for_loops_does_not_mutate_streaming_state(self) -> None:
        """check_for_loops should not modify the streaming analyzer state."""
        config = InternalLoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)

        detector.process_chunk("unique content that should not trigger detection")
        initial_state = detector.get_current_state()

        result = await detector.check_for_loops("standalone inspection content")

        assert result.has_loop is False
        assert detector.get_current_state() == initial_state

    @pytest.mark.asyncio
    async def test_check_for_loops_reports_repeated_length_only(self) -> None:
        """Ensure total_repeated_chars ignores surrounding noise."""

        config = InternalLoopDetectionConfig(
            content_chunk_size=3,
            content_loop_threshold=3,
            max_history_length=50,
        )
        detector = LoopDetector(config=config)

        noisy_content = "xyzabcxyzabcxyzabc"
        result = await detector.check_for_loops(noisy_content)

        assert result.has_loop is True
        assert result.repetitions == config.content_loop_threshold
        assert result.details is not None
        assert result.details["total_repeated_chars"] == 9
        assert result.details["pattern_length"] == 3


class TestLoopDetectionEvent:
    """Test the LoopDetectionEvent class."""

    def test_event_creation(self) -> None:
        """Test creating LoopDetectionEvent instances."""
        import time

        event = LoopDetectionEvent(
            pattern="test pattern",
            repetition_count=5,
            total_length=50,
            confidence=0.9,
            buffer_content="test content",
            timestamp=time.time(),
        )

        assert event.pattern == "test pattern"
        assert event.repetition_count == 5
        assert event.total_length == 50
        assert event.confidence == 0.9
        assert event.buffer_content == "test content"
        assert event.timestamp > 0


if __name__ == "__main__":
    pytest.main([__file__])
