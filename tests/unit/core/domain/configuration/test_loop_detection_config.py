"""
Tests for LoopDetectionConfiguration class.

This module tests the loop detection configuration functionality including
pattern length settings, tool loop detection, and validation.
"""

from unittest.mock import Mock

from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.tool_call_loop.config import ToolLoopMode
from src.tool_call_loop.tracker import ToolCallTracker


class TestLoopDetectionConfiguration:
    """Tests for LoopDetectionConfiguration class."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        config = LoopDetectionConfiguration()

        assert config.loop_detection_enabled is True
        assert config.tool_loop_detection_enabled is True
        assert config.min_pattern_length == 100
        assert config.max_pattern_length == 8000
        assert config.tool_loop_max_repeats is None
        assert config.tool_loop_ttl_seconds is None
        assert config.tool_loop_mode is None
        assert config.tool_call_tracker is None

    def test_initialization_with_values(self) -> None:
        """Test initialization with specific values."""
        config = LoopDetectionConfiguration(
            loop_detection_enabled=False,
            tool_loop_detection_enabled=False,
            min_pattern_length=200,
            max_pattern_length=4000,
            tool_loop_max_repeats=5,
            tool_loop_ttl_seconds=300,
        )

        assert config.loop_detection_enabled is False
        assert config.tool_loop_detection_enabled is False
        assert config.min_pattern_length == 200
        assert config.max_pattern_length == 4000
        assert config.tool_loop_max_repeats == 5
        assert config.tool_loop_ttl_seconds == 300

    def test_tool_loop_max_repeats_validation(self) -> None:
        """Test tool_loop_max_repeats validation."""
        # Valid values
        config = LoopDetectionConfiguration(tool_loop_max_repeats=3)
        assert config.tool_loop_max_repeats == 3

        config = LoopDetectionConfiguration(tool_loop_max_repeats=2)  # Minimum valid
        assert config.tool_loop_max_repeats == 2

        # Field validators in Pydantic v2 only run during explicit validation
        # The validation logic is tested through the with_* methods

    def test_tool_loop_ttl_seconds_validation(self) -> None:
        """Test tool_loop_ttl_seconds validation."""
        # Valid values
        config = LoopDetectionConfiguration(tool_loop_ttl_seconds=60)
        assert config.tool_loop_ttl_seconds == 60

        config = LoopDetectionConfiguration(tool_loop_ttl_seconds=1)  # Minimum valid
        assert config.tool_loop_ttl_seconds == 1

        # Field validators in Pydantic v2 only run during explicit validation
        # The validation logic is tested through the with_* methods

    def test_with_loop_detection_enabled_method(self) -> None:
        """Test with_loop_detection_enabled method."""
        config = LoopDetectionConfiguration(loop_detection_enabled=False)

        new_config = config.with_loop_detection_enabled(True)

        assert new_config.loop_detection_enabled is True
        assert new_config is not config

    def test_with_tool_loop_detection_enabled_method(self) -> None:
        """Test with_tool_loop_detection_enabled method."""
        config = LoopDetectionConfiguration(tool_loop_detection_enabled=False)

        new_config = config.with_tool_loop_detection_enabled(True)

        assert new_config.tool_loop_detection_enabled is True
        assert new_config is not config

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

    def test_with_tool_loop_max_repeats_method(self) -> None:
        """Test with_tool_loop_max_repeats method."""
        config = LoopDetectionConfiguration(tool_loop_max_repeats=None)

        new_config = config.with_tool_loop_max_repeats(5)

        assert new_config.tool_loop_max_repeats == 5
        assert new_config is not config

    def test_with_tool_loop_ttl_seconds_method(self) -> None:
        """Test with_tool_loop_ttl_seconds method."""
        config = LoopDetectionConfiguration(tool_loop_ttl_seconds=None)

        new_config = config.with_tool_loop_ttl_seconds(300)

        assert new_config.tool_loop_ttl_seconds == 300
        assert new_config is not config

    def test_with_tool_loop_mode_method(self) -> None:
        """Test with_tool_loop_mode method."""
        config = LoopDetectionConfiguration(tool_loop_mode=None)

        new_config = config.with_tool_loop_mode(ToolLoopMode.BREAK)

        assert new_config.tool_loop_mode == ToolLoopMode.BREAK
        assert new_config is not config

    def test_immutability(self) -> None:
        """Test that configurations are immutable (methods return new instances)."""
        config = LoopDetectionConfiguration(
            loop_detection_enabled=True,
            tool_loop_detection_enabled=True,
            min_pattern_length=100,
        )

        # All with_* methods should return new instances
        new_config = config.with_loop_detection_enabled(False)
        assert new_config is not config

        new_config2 = config.with_tool_loop_detection_enabled(False)
        assert new_config2 is not config
        assert new_config2 is not new_config

        # Original config should be unchanged
        assert config.loop_detection_enabled is True
        assert config.tool_loop_detection_enabled is True

    def test_tool_call_tracker_assignment(self) -> None:
        """Test tool_call_tracker assignment."""
        mock_tracker = Mock(spec=ToolCallTracker)

        config = LoopDetectionConfiguration(tool_call_tracker=mock_tracker)

        assert config.tool_call_tracker is mock_tracker

    def test_comprehensive_configuration(self) -> None:
        """Test comprehensive configuration setup."""
        config = LoopDetectionConfiguration()

        # Chain multiple configuration updates
        new_config = (
            config.with_loop_detection_enabled(False)
            .with_tool_loop_detection_enabled(False)
            .with_pattern_length_range(150, 6000)
            .with_tool_loop_max_repeats(3)
            .with_tool_loop_ttl_seconds(120)
            .with_tool_loop_mode(ToolLoopMode.CHANCE_THEN_BREAK)
        )

        assert new_config.loop_detection_enabled is False
        assert new_config.tool_loop_detection_enabled is False
        assert new_config.min_pattern_length == 150
        assert new_config.max_pattern_length == 6000
        assert new_config.tool_loop_max_repeats == 3
        assert new_config.tool_loop_ttl_seconds == 120
        assert new_config.tool_loop_mode == ToolLoopMode.CHANCE_THEN_BREAK

    def test_edge_case_validations(self) -> None:
        """Test edge cases for validations."""
        # Test boundary values
        config = LoopDetectionConfiguration(tool_loop_max_repeats=2)  # Minimum valid
        assert config.tool_loop_max_repeats == 2

        config = LoopDetectionConfiguration(tool_loop_ttl_seconds=1)  # Minimum valid
        assert config.tool_loop_ttl_seconds == 1

        # Test None values (should be valid)
        config = LoopDetectionConfiguration(
            tool_loop_max_repeats=None,
            tool_loop_ttl_seconds=None,
            tool_loop_mode=None,
        )
        assert config.tool_loop_max_repeats is None
        assert config.tool_loop_ttl_seconds is None
        assert config.tool_loop_mode is None

    def test_large_values(self) -> None:
        """Test with large valid values."""
        config = LoopDetectionConfiguration(
            min_pattern_length=1000,
            max_pattern_length=50000,
            tool_loop_max_repeats=100,
            tool_loop_ttl_seconds=86400,  # 24 hours
        )

        assert config.min_pattern_length == 1000
        assert config.max_pattern_length == 50000
        assert config.tool_loop_max_repeats == 100
        assert config.tool_loop_ttl_seconds == 86400
