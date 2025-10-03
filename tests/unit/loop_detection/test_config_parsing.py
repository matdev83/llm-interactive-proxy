"""Tests for loop detection config parsing helpers."""

from src.loop_detection.config import LoopDetectionConfig


class TestLoopDetectionConfigParsing:
    """Ensure dictionary parsing handles loose boolean values."""

    def test_from_dict_handles_string_booleans(self) -> None:
        """String representations of booleans should be parsed predictably."""

        config_false = LoopDetectionConfig.from_dict({"enabled": "false"})
        assert config_false.enabled is False

        config_true = LoopDetectionConfig.from_dict({"enabled": "TRUE"})
        assert config_true.enabled is True

    def test_from_dict_handles_numeric_booleans(self) -> None:
        """Numeric values should follow standard truthiness rules."""

        config_zero = LoopDetectionConfig.from_dict({"enabled": 0})
        assert config_zero.enabled is False

        config_one = LoopDetectionConfig.from_dict({"enabled": 1})
        assert config_one.enabled is True
