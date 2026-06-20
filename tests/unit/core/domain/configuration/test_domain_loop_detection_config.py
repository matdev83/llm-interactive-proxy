"""Tests for LoopDetectionConfiguration class."""

from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)


class TestLoopDetectionConfiguration:
    """Tests for generic reply/content loop detection configuration."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        config = LoopDetectionConfiguration()

        assert config.loop_detection_enabled is False
        assert config.min_pattern_length == 100
        assert config.max_pattern_length == 8000

    def test_initialization_with_values(self) -> None:
        """Test initialization with specific values."""
        config = LoopDetectionConfiguration(
            loop_detection_enabled=True,
            min_pattern_length=200,
            max_pattern_length=4000,
        )

        assert config.loop_detection_enabled is True
        assert config.min_pattern_length == 200
        assert config.max_pattern_length == 4000

    def test_with_loop_detection_enabled_method(self) -> None:
        """Test with_loop_detection_enabled method."""
        config = LoopDetectionConfiguration(loop_detection_enabled=False)

        new_config = config.with_loop_detection_enabled(True)

        assert new_config.loop_detection_enabled is True
        assert new_config is not config
        assert config.loop_detection_enabled is False

    def test_with_pattern_length_range_method(self) -> None:
        """Test with_pattern_length_range method."""
        config = LoopDetectionConfiguration(
            min_pattern_length=100,
            max_pattern_length=8000,
        )

        new_config = config.with_pattern_length_range(200, 4000)

        assert new_config.min_pattern_length == 200
        assert new_config.max_pattern_length == 4000
        assert new_config is not config

    def test_comprehensive_configuration(self) -> None:
        """Test chaining remaining generic loop-detection config updates."""
        config = LoopDetectionConfiguration()

        new_config = config.with_loop_detection_enabled(True).with_pattern_length_range(
            150, 6000
        )

        assert new_config.loop_detection_enabled is True
        assert new_config.min_pattern_length == 150
        assert new_config.max_pattern_length == 6000

    def test_large_values(self) -> None:
        """Test with large valid values."""
        config = LoopDetectionConfiguration(
            min_pattern_length=1000,
            max_pattern_length=50000,
        )

        assert config.min_pattern_length == 1000
        assert config.max_pattern_length == 50000
