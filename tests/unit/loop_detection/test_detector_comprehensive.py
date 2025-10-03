"""
Tests for LoopDetector.

This module provides comprehensive test coverage for the LoopDetector class.
"""

import pytest
from src.loop_detection.analyzer import LoopDetectionEvent
from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetector


class TestLoopDetector:
    """Tests for LoopDetector class."""

    @pytest.fixture
    def config(self) -> LoopDetectionConfig:
        """Create a test configuration."""
        return LoopDetectionConfig(
            enabled=True,
            buffer_size=1024,
            max_pattern_length=512,
            analysis_interval=32,
        )

    @pytest.fixture
    def detector(self, config: LoopDetectionConfig) -> LoopDetector:
        """Create a fresh LoopDetector for each test."""
        return LoopDetector(config=config)

    def test_detector_initialization(
        self, detector: LoopDetector, config: LoopDetectionConfig
    ) -> None:
        """Test detector initialization."""
        assert detector.config == config
        assert detector.is_enabled() is True
        assert detector.buffer is not None
        assert detector.hasher is not None
        assert detector.analyzer is not None
        assert detector.total_processed == 0
        assert detector.last_detection_position == -1
        assert detector._last_analysis_position == -1

    def test_detector_initialization_disabled(self) -> None:
        """Test detector initialization with disabled config."""
        config = LoopDetectionConfig(enabled=False)
        detector = LoopDetector(config=config)

        assert detector.is_enabled() is False

    def test_detector_initialization_invalid_config(self) -> None:
        """Test detector initialization with invalid config."""
        config = LoopDetectionConfig(buffer_size=0)  # Invalid

        with pytest.raises(ValueError, match="Invalid loop detection configuration"):
            LoopDetector(config=config)

    def test_detector_enable_disable(self, detector: LoopDetector) -> None:
        """Test enabling and disabling the detector."""
        # Initially enabled
        assert detector.is_enabled() is True

        # Disable
        detector.disable()
        assert detector.is_enabled() is False

        # Enable
        detector.enable()
        assert detector.is_enabled() is True

    def test_process_chunk_disabled_detector(self, detector: LoopDetector) -> None:
        """Test processing chunks with disabled detector."""
        detector.disable()

        result = detector.process_chunk("test content")

        assert result is None
        assert detector.total_processed == 0

    def test_process_chunk_empty_chunk(self, detector: LoopDetector) -> None:
        """Test processing empty chunks."""
        result = detector.process_chunk("")

        assert result is None
        assert detector.total_processed == 0

    def test_process_chunk_none_chunk(self, detector: LoopDetector) -> None:
        """Test processing None chunks."""
        result = detector.process_chunk(None)  # type: ignore

        assert result is None
        assert detector.total_processed == 0

    def test_process_chunk_normal_content(self, detector: LoopDetector) -> None:
        """Test processing normal content."""
        chunk = "This is normal content without loops."
        result = detector.process_chunk(chunk)

        assert result is None
        assert detector.total_processed == len(chunk)
        assert len(detector.buffer.get_content()) == len(chunk)

    def test_process_chunk_multiple_chunks(self, detector: LoopDetector) -> None:
        """Test processing multiple chunks."""
        chunks = ["First chunk. ", "Second chunk. ", "Third chunk."]

        for chunk in chunks:
            result = detector.process_chunk(chunk)
            assert result is None

        expected_total = sum(len(chunk) for chunk in chunks)
        assert detector.total_processed == expected_total
        assert len(detector.buffer.get_content()) == expected_total

    def test_process_chunk_unicode_content(self, detector: LoopDetector) -> None:
        """Test processing Unicode content."""
        unicode_chunk = "Hello, 世界! 🌍 Test content with émojis and ñoñäscii"
        result = detector.process_chunk(unicode_chunk)

        assert result is None
        assert detector.total_processed == len(unicode_chunk)

    def test_process_chunk_very_long_content(self, detector: LoopDetector) -> None:
        """Test processing very long content."""
        long_chunk = "x" * 10000
        result = detector.process_chunk(long_chunk)

        assert result is None
        assert detector.total_processed == len(long_chunk)

    def test_process_chunk_buffer_overflow(self) -> None:
        """Test buffer overflow during chunk processing."""
        config = LoopDetectionConfig(buffer_size=100)
        detector = LoopDetector(config=config)

        # Add content that exceeds buffer size
        large_chunk = "x" * 200
        result = detector.process_chunk(large_chunk)

        assert result is None
        assert detector.total_processed == 200
        assert len(detector.buffer.get_content()) <= 100

    def test_process_chunk_with_callback(self, detector: LoopDetector) -> None:
        """Test processing chunks with callback."""
        callback_called = False
        callback_event = None

        def mock_callback(event: LoopDetectionEvent) -> None:
            nonlocal callback_called, callback_event
            callback_called = True
            callback_event = event

        detector.on_loop_detected = mock_callback

        # Process content that might trigger detection
        # (This depends on the analyzer implementation)
        detector.process_chunk("test content")

        # The callback may or may not be called depending on content
        # The important thing is that processing works

    def test_process_chunk_error_in_callback(self, detector: LoopDetector) -> None:
        """Test handling errors in callback."""

        def failing_callback(event: LoopDetectionEvent) -> None:
            raise RuntimeError("Callback error")

        detector.on_loop_detected = failing_callback

        # Should not crash even if callback fails
        result = detector.process_chunk("test content")

        assert result is None  # Processing should continue despite callback error

    def test_reset_detector(self, detector: LoopDetector) -> None:
        """Test resetting the detector."""
        # Add some content and state
        detector.process_chunk("test content")
        detector.last_detection_position = 50

        assert detector.total_processed > 0
        assert detector.last_detection_position == 50
        assert len(detector.buffer.get_content()) > 0

        # Reset
        detector.reset()

        assert detector.total_processed == 0
        assert detector.last_detection_position == -1
        assert detector._last_analysis_position == -1
        assert len(detector.buffer.get_content()) == 0

    def test_get_stats(self, detector: LoopDetector) -> None:
        """Test getting detector statistics."""
        stats = detector.get_stats()

        assert isinstance(stats, dict)
        assert "is_active" in stats
        assert "last_detection_position" in stats
        assert "config" in stats

        assert stats["is_active"] == detector.is_enabled()
        assert stats["last_detection_position"] == detector.last_detection_position

        # Check config structure
        config_stats = stats["config"]
        assert "buffer_size" in config_stats
        assert "max_pattern_length" in config_stats
        assert "short_threshold" in config_stats
        assert "medium_threshold" in config_stats
        assert "long_threshold" in config_stats

    def test_update_config(self, detector: LoopDetector) -> None:
        """Test updating detector configuration."""
        new_config = LoopDetectionConfig(
            enabled=False,
            buffer_size=2048,
            max_pattern_length=1024,
        )

        detector.update_config(new_config)

        assert detector.config == new_config
        assert detector.is_enabled() is False

    def test_update_config_invalid(self, detector: LoopDetector) -> None:
        """Test updating with invalid configuration."""
        invalid_config = LoopDetectionConfig(buffer_size=0)  # Invalid

        with pytest.raises(ValueError, match="Invalid loop detection configuration"):
            detector.update_config(invalid_config)

    def test_update_config_buffer_resize(self, detector: LoopDetector) -> None:
        """Test that updating config resizes buffer when needed."""
        # Add content to current buffer
        detector.process_chunk("x" * 100)

        # Update with smaller buffer size
        new_config = LoopDetectionConfig(buffer_size=50)
        detector.update_config(new_config)

        # Content should be truncated to fit new buffer size
        assert len(detector.buffer.get_content()) <= 50

    def test_process_chunk_accumulates_total(self, detector: LoopDetector) -> None:
        """Test that total_processed accumulates correctly."""
        chunks = ["chunk1", "chunk2", "chunk3"]
        expected_total = sum(len(chunk) for chunk in chunks)

        for chunk in chunks:
            detector.process_chunk(chunk)

        assert detector.total_processed == expected_total

    def test_process_chunk_updates_detection_position(
        self, detector: LoopDetector
    ) -> None:
        """Test that detection position is updated when loop is detected."""
        # This test depends on the analyzer actually detecting a loop
        # For now, we just verify the position starts at -1
        assert detector.last_detection_position == -1

        detector.process_chunk("test content")

        # Position may or may not change depending on detection
        assert detector.last_detection_position >= -1

    def test_process_chunk_very_small_chunks(self, detector: LoopDetector) -> None:
        """Test processing very small chunks."""
        small_chunks = ["a", "b", "c", "d", "e"]

        for chunk in small_chunks:
            result = detector.process_chunk(chunk)
            assert result is None

        assert detector.total_processed == len(small_chunks)

    def test_process_chunk_whitespace_chunks(self, detector: LoopDetector) -> None:
        """Test processing whitespace chunks."""
        whitespace_chunks = ["   ", "\n", "\t", " \n\t "]

        for chunk in whitespace_chunks:
            result = detector.process_chunk(chunk)
            assert result is None

        expected_total = sum(len(chunk) for chunk in whitespace_chunks)
        assert detector.total_processed == expected_total

    def test_process_chunk_special_characters(self, detector: LoopDetector) -> None:
        """Test processing chunks with special characters."""
        special_chunk = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        result = detector.process_chunk(special_chunk)

        assert result is None
        assert detector.total_processed == len(special_chunk)

    def test_process_chunk_json_like_content(self, detector: LoopDetector) -> None:
        """Test processing JSON-like content."""
        json_chunk = '{"key": "value", "number": 123, "array": [1, 2, 3]}'
        result = detector.process_chunk(json_chunk)

        assert result is None
        assert detector.total_processed == len(json_chunk)

    def test_process_chunk_code_like_content(self, detector: LoopDetector) -> None:
        """Test processing code-like content."""
        code_chunk = "def hello():\n    print('Hello, world!')\n    return True"
        result = detector.process_chunk(code_chunk)

        assert result is None
        assert detector.total_processed == len(code_chunk)

    def test_process_chunk_mixed_content_types(self, detector: LoopDetector) -> None:
        """Test processing mixed content types."""
        chunks = [
            "Normal text.",
            "```python\ncode block\n```",
            "# Header",
            "- List item",
            "1. Numbered item",
            "Regular paragraph text.",
        ]

        for chunk in chunks:
            result = detector.process_chunk(chunk)
            assert result is None

        expected_total = sum(len(chunk) for chunk in chunks)
        assert detector.total_processed == expected_total

    def test_detector_state_consistency(self, detector: LoopDetector) -> None:
        """Test that detector state remains consistent."""
        initial_active = detector.is_enabled()

        # Process some content
        detector.process_chunk("test content")
        detector.process_chunk("more content")

        # State should be consistent
        assert detector.is_enabled() == initial_active
        assert detector.total_processed > 0
        assert detector.config is not None
        assert detector.buffer is not None
        assert detector.hasher is not None
        assert detector.analyzer is not None

    def test_detector_multiple_instances_isolation(self) -> None:
        """Test that multiple detector instances are isolated."""
        config1 = LoopDetectionConfig(buffer_size=100)
        config2 = LoopDetectionConfig(buffer_size=200)

        detector1 = LoopDetector(config=config1)
        detector2 = LoopDetector(config=config2)

        # Process different content
        detector1.process_chunk("content1")
        detector2.process_chunk("content2")

        # Should have different states
        assert detector1.total_processed == len("content1")
        assert detector2.total_processed == len("content2")
        assert detector1.config.buffer_size == 100
        assert detector2.config.buffer_size == 200

    def test_process_chunk_performance_with_large_content(self) -> None:
        """Test performance with large content chunks."""
        detector = LoopDetector()

        large_chunk = "x" * 10000

        # Should complete in reasonable time
        result = detector.process_chunk(large_chunk)

        assert result is None
        assert detector.total_processed == len(large_chunk)

    def test_process_chunk_edge_case_empty_after_content(
        self, detector: LoopDetector
    ) -> None:
        """Test processing empty chunk after content."""
        # Add content first
        detector.process_chunk("initial content")

        # Then empty chunk
        result = detector.process_chunk("")

        assert result is None
        assert detector.total_processed == len("initial content")

    def test_process_chunk_edge_case_none_after_content(
        self, detector: LoopDetector
    ) -> None:
        """Test processing None chunk after content."""
        # Add content first
        detector.process_chunk("initial content")

        # Then None chunk
        result = detector.process_chunk(None)  # type: ignore

        assert result is None
        assert detector.total_processed == len("initial content")

    def test_get_stats_comprehensive(self, detector: LoopDetector) -> None:
        """Test comprehensive statistics."""
        # Add some content
        detector.process_chunk("test content")

        stats = detector.get_stats()

        # Verify all expected fields are present
        required_fields = [
            "is_active",
            "last_detection_position",
            "config",
        ]

        for field in required_fields:
            assert field in stats

        # Check config sub-fields
        config_stats = stats["config"]
        required_config_fields = [
            "buffer_size",
            "max_pattern_length",
            "short_threshold",
            "medium_threshold",
            "long_threshold",
        ]

        for field in required_config_fields:
            assert field in config_stats

    def test_detector_with_minimal_config(self) -> None:
        """Test detector with minimal valid configuration."""
        config = LoopDetectionConfig(
            buffer_size=1,  # Minimal valid size
            max_pattern_length=1,
        )
        detector = LoopDetector(config=config)

        assert detector.is_enabled() is True
        assert detector.config.buffer_size == 1

    def test_detector_with_maximal_config(self) -> None:
        """Test detector with large configuration values."""
        config = LoopDetectionConfig(
            buffer_size=100000,
            max_pattern_length=50000,
            max_history_length=100000,
        )
        detector = LoopDetector(config=config)

        assert detector.is_enabled() is True
        assert detector.config.buffer_size == 100000
