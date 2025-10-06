"""
Tests for Loop Detection Configuration.

This module tests the loop detection configuration classes and validation.
"""

import pytest
from src.loop_detection.config import (
    InternalLoopDetectionConfig,
    PatternThresholds,
)


class TestPatternThresholds:
    """Tests for PatternThresholds class."""

    def test_pattern_thresholds_creation(self) -> None:
        """Test PatternThresholds creation with valid values."""
        thresholds = PatternThresholds(min_repetitions=5, min_total_length=100)

        assert thresholds.min_repetitions == 5
        assert thresholds.min_total_length == 100

    def test_pattern_thresholds_default_values(self) -> None:
        """Test PatternThresholds requires explicit values."""
        # PatternThresholds is a dataclass without defaults
        with pytest.raises(TypeError):
            PatternThresholds()

    def test_pattern_thresholds_as_dict(self) -> None:
        """Test PatternThresholds can be converted to dictionary."""
        thresholds = PatternThresholds(min_repetitions=3, min_total_length=50)

        data = {
            "min_repetitions": thresholds.min_repetitions,
            "min_total_length": thresholds.min_total_length,
        }

        assert data["min_repetitions"] == 3
        assert data["min_total_length"] == 50


class TestInternalLoopDetectionConfig:
    """Tests for InternalLoopDetectionConfig class."""

    def test_default_config_creation(self) -> None:
        """Test InternalLoopDetectionConfig creation with defaults."""
        config = InternalLoopDetectionConfig()

        assert config.enabled is True
        assert config.buffer_size == 16384
        assert config.max_pattern_length == 8192
        assert config.analysis_interval == 64
        assert config.content_chunk_size == 100
        assert config.content_loop_threshold == 6
        assert config.max_history_length == 4096

    def test_custom_config_creation(self) -> None:
        """Test InternalLoopDetectionConfig creation with custom values."""
        config = InternalLoopDetectionConfig(
            enabled=False,
            buffer_size=1024,
            max_pattern_length=2048,
            analysis_interval=32,
            content_chunk_size=25,
            content_loop_threshold=5,
            max_history_length=500,
        )

        assert config.enabled is False
        assert config.buffer_size == 1024
        assert config.max_pattern_length == 2048
        assert config.analysis_interval == 32
        assert config.content_chunk_size == 25
        assert config.content_loop_threshold == 5
        assert config.max_history_length == 500

    def test_default_thresholds_initialization(self) -> None:
        """Test that default thresholds are properly initialized."""
        config = InternalLoopDetectionConfig()

        assert isinstance(config.pattern_thresholds, dict)
        assert "exact_match" in config.pattern_thresholds
        assert "semantic_match" in config.pattern_thresholds

        exact_thresholds = config.pattern_thresholds["exact_match"]
        semantic_thresholds = config.pattern_thresholds["semantic_match"]

        assert isinstance(exact_thresholds, PatternThresholds)
        assert exact_thresholds.min_repetitions == 3
        assert exact_thresholds.min_total_length == 100

        assert isinstance(semantic_thresholds, PatternThresholds)
        assert semantic_thresholds.min_repetitions == 4
        assert semantic_thresholds.min_total_length == 200

    def test_validate_catches_non_positive_chunk_settings(self) -> None:
        """Validate rejects non-positive chunk configuration values."""
        config = InternalLoopDetectionConfig(
            content_chunk_size=0,
            content_loop_threshold=-2,
            max_history_length=0,
        )

        errors = config.validate()

        assert "content_chunk_size must be positive" in errors
        assert "content_loop_threshold must be positive" in errors
        assert "max_history_length must be positive" in errors
