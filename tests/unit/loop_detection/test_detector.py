"""
Unit tests for the main LoopDetector class.
"""

import pytest

from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetectionEvent, LoopDetector


class TestLoopDetector:
    """Test the LoopDetector class."""
    
    def test_detector_initialization(self):
        """Test that detector initializes correctly."""
        config = LoopDetectionConfig(enabled=True, buffer_size=1024)
        detector = LoopDetector(config=config)
        
        assert detector.is_enabled() == True
        assert detector.config.buffer_size == 1024
    
    def test_detector_disabled(self):
        """Test that disabled detector doesn't process chunks."""
        config = LoopDetectionConfig(enabled=False)
        detector = LoopDetector(config=config)
        
        # Should not process when disabled
        result = detector.process_chunk("test test test test test")
        assert result is None
    
    def test_simple_loop_detection(self):
        """Test detection of simple loops."""
        config = LoopDetectionConfig(
            enabled=True,
            buffer_size=1024,
            max_pattern_length=200
        )
        # Lower thresholds for testing
        config.short_pattern_threshold.min_repetitions = 3
        config.short_pattern_threshold.min_total_length = 10
        config.medium_pattern_threshold.min_repetitions = 2
        config.medium_pattern_threshold.min_total_length = 20
        
        events = []
        def on_loop_detected(event):
            events.append(event)
        
        detector = LoopDetector(config=config, on_loop_detected=on_loop_detected)
        
        # Send a clearly looping pattern of >=100 chars repeated 3 times
        long_block = "ERROR " * 20  # 120 chars
        loop_text = long_block * 3

        result = detector.process_chunk(loop_text)
        
        # Debug: print what was detected
        print(f"Result: {result}")
        print(f"Events: {events}")
        
        # Should detect the loop
        assert result is not None or len(events) > 0, "Loop not detected for 120-char repeated block"
        
        if result:
            assert isinstance(result, LoopDetectionEvent)
            assert result.repetition_count >= 3
        
        if events:
            assert isinstance(events[0], LoopDetectionEvent)
            assert events[0].repetition_count >= 3
    
    def test_no_false_positive_normal_text(self):
        """Test that normal text doesn't trigger false positives."""
        config = LoopDetectionConfig(enabled=True)
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
    
    def test_detector_reset(self):
        """Test that detector reset works correctly."""
        config = LoopDetectionConfig(enabled=True)
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
    
    def test_detector_enable_disable(self):
        """Test enabling and disabling the detector."""
        config = LoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)
        
        assert detector.is_enabled() == True
        
        detector.disable()
        assert detector.is_enabled() == False
        
        detector.enable()
        assert detector.is_enabled() == True
    
    def test_detector_stats(self):
        """Test that detector statistics are correct."""
        config = LoopDetectionConfig(enabled=True, buffer_size=512)
        detector = LoopDetector(config=config)
        
        stats = detector.get_stats()
        
        assert stats["is_active"] == True
        # Note: total_processed and buffer_size are not directly in stats dict
        # They're tracked separately in the detector
        assert stats["config"]["buffer_size"] == 512
    
    def test_minimum_content_threshold(self):
        """Test that detector requires minimum content before analyzing."""
        config = LoopDetectionConfig(enabled=True)
        detector = LoopDetector(config=config)
        
        # Very short text should not trigger analysis
        result = detector.process_chunk("a")
        assert result is None
        
        result = detector.process_chunk("ab")
        assert result is None
    
    def test_config_validation(self):
        """Test that invalid configurations are rejected."""
        # Invalid buffer size
        with pytest.raises(ValueError):
            config = LoopDetectionConfig(enabled=True, buffer_size=-1)
            LoopDetector(config=config)
        
        # Invalid max pattern length
        with pytest.raises(ValueError):
            config = LoopDetectionConfig(enabled=True, max_pattern_length=0)
            LoopDetector(config=config)


class TestLoopDetectionEvent:
    """Test the LoopDetectionEvent class."""
    
    def test_event_creation(self):
        """Test creating LoopDetectionEvent instances."""
        import time
        
        event = LoopDetectionEvent(
            pattern="test pattern",
            repetition_count=5,
            total_length=50,
            confidence=0.9,
            buffer_content="test content",
            timestamp=time.time()
        )
        
        assert event.pattern == "test pattern"
        assert event.repetition_count == 5
        assert event.total_length == 50
        assert event.confidence == 0.9
        assert event.buffer_content == "test content"
        assert event.timestamp > 0


if __name__ == "__main__":
    pytest.main([__file__])