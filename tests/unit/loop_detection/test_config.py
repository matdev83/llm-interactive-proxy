"""
Tests for Loop Detection Configuration.

This module tests the loop detection configuration classes and validation.
"""

import pytest
from typing import Any

from src.loop_detection.config import (
    PatternThresholds,
    LoopDetectionConfig,
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


class TestLoopDetectionConfig:
    """Tests for LoopDetectionConfig class."""

    def test_default_config_creation(self) -> None:
        """Test LoopDetectionConfig creation with defaults."""
        config = LoopDetectionConfig()

        assert config.enabled is True
        assert config.buffer_size == 16384
        assert config.max_pattern_length == 8192
        assert config.analysis_interval == 64
        assert config.content_chunk_size == 50
        assert config.content_loop_threshold == 10
        assert config.max_history_length == 1000

    def test_custom_config_creation(self) -> None:
        """Test LoopDetectionConfig creation with custom values."""
        config = LoopDetectionConfig(
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
        config = LoopDetectionConfig()

        # Check that thresholds are initialized
        assert config.short_pattern_threshold is not None
        assert config.medium_pattern_threshold is not None
        assert config.long_pattern_threshold is not None

        # Check default values
        assert config.short_pattern_threshold.min_repetitions == 8
        assert config.short_pattern_threshold.min_total_length == 100

        assert config.medium_pattern_threshold.min_repetitions == 4
        assert config.medium_pattern_threshold.min_total_length == 100

        assert config.long_pattern_threshold.min_repetitions == 3
        assert config.long_pattern_threshold.min_total_length == 100

    def test_custom_thresholds(self) -> None:
        """Test setting custom pattern thresholds."""
        short_threshold = PatternThresholds(min_repetitions=5, min_total_length=50)
        medium_threshold = PatternThresholds(min_repetitions=3, min_total_length=75)
        long_threshold = PatternThresholds(min_repetitions=2, min_total_length=150)

        config = LoopDetectionConfig(
            short_pattern_threshold=short_threshold,
            medium_pattern_threshold=medium_threshold,
            long_pattern_threshold=long_threshold,
        )

        assert config.short_pattern_threshold.min_repetitions == 5
        assert config.medium_pattern_threshold.min_repetitions == 3
        assert config.long_pattern_threshold.min_repetitions == 2

    def test_whitelist_initialization(self) -> None:
        """Test whitelist initialization."""
        config = LoopDetectionConfig()

        # Whitelist is initialized with default patterns
        assert config.whitelist == ["...", "---", "===", "```"]

    def test_custom_whitelist(self) -> None:
        """Test setting custom whitelist."""
        whitelist = ["pattern1", "pattern2", "pattern3"]
        config = LoopDetectionConfig(whitelist=whitelist)

        assert config.whitelist == whitelist

    def test_config_validation_success(self) -> None:
        """Test config validation with valid values."""
        config = LoopDetectionConfig()

        errors = config.validate()
        assert errors == []

    def test_config_validation_buffer_size_too_small(self) -> None:
        """Test config validation with buffer size too small."""
        config = LoopDetectionConfig(buffer_size=0)

        errors = config.validate()
        assert len(errors) > 0
        assert "buffer_size must be positive" in errors

    def test_config_validation_max_pattern_length_too_large(self) -> None:
        """Test config validation with max pattern length too large."""
        config = LoopDetectionConfig(
            buffer_size=1000,
            max_pattern_length=0  # Invalid (must be positive)
        )

        errors = config.validate()
        assert len(errors) > 0
        assert "max_pattern_length must be positive" in errors

    def test_config_validation_content_chunk_size_valid(self) -> None:
        """Test config validation with valid content chunk size."""
        config = LoopDetectionConfig(
            max_pattern_length=1000,
            content_chunk_size=500  # Valid size
        )

        errors = config.validate()
        assert len(errors) == 0  # Should be valid

    def test_config_validation_negative_values(self) -> None:
        """Test config validation with negative values."""
        config = LoopDetectionConfig(
            buffer_size=-100,
            max_pattern_length=-200,
            content_chunk_size=-50,
            content_loop_threshold=-10,
        )

        errors = config.validate()
        assert len(errors) > 0

    def test_config_validation_zero_values(self) -> None:
        """Test config validation with zero values."""
        config = LoopDetectionConfig(
            buffer_size=0,
            max_pattern_length=0,
            content_chunk_size=0,
            content_loop_threshold=0,
        )

        errors = config.validate()
        assert len(errors) > 0

    def test_config_validation_thresholds(self) -> None:
        """Test config validation with invalid thresholds."""
        # Test negative repetitions
        invalid_short = PatternThresholds(min_repetitions=-1, min_total_length=100)
        config = LoopDetectionConfig(short_pattern_threshold=invalid_short)

        errors = config.validate()
        assert len(errors) > 0

        # Test negative length
        invalid_medium = PatternThresholds(min_repetitions=4, min_total_length=-50)
        config = LoopDetectionConfig(medium_pattern_threshold=invalid_medium)

        errors = config.validate()
        assert len(errors) > 0

    def test_config_as_dict_conversion(self) -> None:
        """Test converting config to dictionary."""
        config = LoopDetectionConfig(
            enabled=True,
            buffer_size=2048,
            max_pattern_length=4096,
        )

        # Should be able to access all attributes
        assert config.enabled is True
        assert config.buffer_size == 2048
        assert config.max_pattern_length == 4096

    def test_config_mutability(self) -> None:
        """Test that config is mutable after creation."""
        config = LoopDetectionConfig()

        # Should be able to modify after creation (not frozen)
        original_value = config.buffer_size
        config.buffer_size = 4096
        assert config.buffer_size == 4096

        # Restore original value
        config.buffer_size = original_value

    def test_config_equality(self) -> None:
        """Test config equality comparison."""
        config1 = LoopDetectionConfig(enabled=True, buffer_size=1024)
        config2 = LoopDetectionConfig(enabled=True, buffer_size=1024)
        config3 = LoopDetectionConfig(enabled=False, buffer_size=1024)

        assert config1 == config2
        assert config1 != config3

    def test_config_not_hashable(self) -> None:
        """Test that config is not hashable (mutable dataclass)."""
        config = LoopDetectionConfig()

        # Should not be hashable (mutable dataclass)
        with pytest.raises(TypeError):
            config_set = {config}

        with pytest.raises(TypeError):
            config_dict = {config: "value"}

    def test_config_string_representation(self) -> None:
        """Test config string representation."""
        config = LoopDetectionConfig(enabled=True, buffer_size=1024)

        str_repr = str(config)
        assert "LoopDetectionConfig" in str_repr
        assert "enabled=True" in str_repr
        assert "buffer_size=1024" in str_repr

    def test_config_repr(self) -> None:
        """Test config repr representation."""
        config = LoopDetectionConfig()

        repr_str = repr(config)
        assert "LoopDetectionConfig" in repr_str

    def test_config_field_access(self) -> None:
        """Test accessing all config fields."""
        config = LoopDetectionConfig()

        # Test all fields are accessible
        assert hasattr(config, "enabled")
        assert hasattr(config, "buffer_size")
        assert hasattr(config, "max_pattern_length")
        assert hasattr(config, "analysis_interval")
        assert hasattr(config, "content_chunk_size")
        assert hasattr(config, "content_loop_threshold")
        assert hasattr(config, "max_history_length")
        assert hasattr(config, "short_pattern_threshold")
        assert hasattr(config, "medium_pattern_threshold")
        assert hasattr(config, "long_pattern_threshold")
        assert hasattr(config, "whitelist")

    def test_config_with_extreme_values(self) -> None:
        """Test config with extreme but valid values."""
        # Very large values
        config = LoopDetectionConfig(
            buffer_size=1000000,
            max_pattern_length=500000,
            max_history_length=100000,
        )

        errors = config.validate()
        assert errors == []  # Should be valid

        # Very small but valid values
        config = LoopDetectionConfig(
            buffer_size=100,
            max_pattern_length=50,
            content_chunk_size=10,
            max_history_length=50,
        )

        errors = config.validate()
        assert errors == []  # Should be valid

    def test_config_edge_case_empty_whitelist(self) -> None:
        """Test config with empty whitelist."""
        config = LoopDetectionConfig(whitelist=[])

        assert config.whitelist == []

    def test_config_edge_case_none_whitelist(self) -> None:
        """Test config with None whitelist."""
        config = LoopDetectionConfig(whitelist=None)

        # Should be initialized with default patterns
        assert config.whitelist == ["...", "---", "===", "```"]
