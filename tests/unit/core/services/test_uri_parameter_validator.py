"""Unit tests for URI parameter validator."""

import logging

import pytest
from src.core.services.uri_parameter_validator import URIParameterValidator


class TestURIParameterValidator:
    """Test cases for URI parameter validation and normalization."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance for testing."""
        return URIParameterValidator()

    # ========================================================================
    # Temperature Validation Tests
    # ========================================================================

    def test_temperature_valid_range_lower_bound(self, validator):
        """Test temperature validation at lower bound (0.0)."""
        params = {"temperature": "0.0"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.0}
        assert errors == []

    def test_temperature_valid_range_upper_bound(self, validator):
        """Test temperature validation at upper bound (2.0)."""
        params = {"temperature": "2.0"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 2.0}
        assert errors == []

    def test_temperature_valid_range_middle(self, validator):
        """Test temperature validation in middle of range."""
        params = {"temperature": "0.7"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.7}
        assert errors == []

    def test_temperature_valid_range_decimal_precision(self, validator):
        """Test temperature validation with high decimal precision."""
        params = {"temperature": "0.123456"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.123456}
        assert errors == []

    def test_temperature_out_of_range_below_minimum(self, validator):
        """Test temperature validation below minimum (negative value)."""
        params = {"temperature": "-0.5"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "temperature" in errors[0]
        assert "below minimum" in errors[0]

    def test_temperature_out_of_range_above_maximum(self, validator):
        """Test temperature validation above maximum."""
        params = {"temperature": "3.5"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "temperature" in errors[0]
        assert "above maximum" in errors[0]

    def test_temperature_invalid_type_string(self, validator):
        """Test temperature validation with non-numeric string."""
        params = {"temperature": "invalid"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "temperature" in errors[0]
        assert "valid number" in errors[0]

    def test_temperature_invalid_type_none(self, validator):
        """Test temperature validation with None value."""
        params = {"temperature": None}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "temperature" in errors[0]

    def test_temperature_integer_value(self, validator):
        """Test temperature validation with integer value (should convert to float)."""
        params = {"temperature": "1"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 1.0}
        assert errors == []

    # ========================================================================
    # Reasoning Effort Validation Tests
    # ========================================================================

    def test_reasoning_effort_valid_low(self, validator):
        """Test reasoning_effort validation with 'low' value."""
        params = {"reasoning_effort": "low"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"reasoning_effort": "low"}
        assert errors == []

    def test_reasoning_effort_valid_medium(self, validator):
        """Test reasoning_effort validation with 'medium' value."""
        params = {"reasoning_effort": "medium"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"reasoning_effort": "medium"}
        assert errors == []

    def test_reasoning_effort_valid_high(self, validator):
        """Test reasoning_effort validation with 'high' value."""
        params = {"reasoning_effort": "high"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"reasoning_effort": "high"}
        assert errors == []

    def test_reasoning_effort_invalid_value(self, validator):
        """Test reasoning_effort validation with invalid value."""
        params = {"reasoning_effort": "extreme"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]
        assert "not in allowed values" in errors[0]

    def test_reasoning_effort_invalid_case(self, validator):
        """Test reasoning_effort validation is case-sensitive."""
        params = {"reasoning_effort": "Low"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]
        assert "not in allowed values" in errors[0]

    def test_reasoning_effort_empty_string(self, validator):
        """Test reasoning_effort validation with empty string."""
        params = {"reasoning_effort": ""}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]

    # ========================================================================
    # Unknown Parameter Handling Tests
    # ========================================================================

    def test_unknown_parameter_single(self, validator, caplog):
        """Test that unknown parameters are logged as warnings and ignored."""
        params = {"unknown_param": "value"}

        with caplog.at_level(logging.WARNING):
            normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert errors == []
        assert "Unknown URI parameter 'unknown_param'" in caplog.text
        assert "Supported parameters:" in caplog.text

    def test_unknown_parameter_multiple(self, validator, caplog):
        """Test that multiple unknown parameters are all logged."""
        params = {"unknown1": "value1", "unknown2": "value2"}

        with caplog.at_level(logging.WARNING):
            normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert errors == []
        assert "unknown1" in caplog.text
        assert "unknown2" in caplog.text

    def test_unknown_parameter_mixed_with_valid(self, validator, caplog):
        """Test that unknown parameters don't affect valid parameter processing."""
        params = {
            "temperature": "0.5",
            "unknown_param": "value",
            "reasoning_effort": "high",
        }

        with caplog.at_level(logging.WARNING):
            normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.5, "reasoning_effort": "high"}
        assert errors == []
        assert "unknown_param" in caplog.text

    # ========================================================================
    # Normalization Tests
    # ========================================================================

    def test_normalization_multiple_valid_parameters(self, validator):
        """Test normalization of multiple valid parameters."""
        params = {"temperature": "0.8", "reasoning_effort": "medium"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.8, "reasoning_effort": "medium"}
        assert errors == []

    def test_normalization_type_conversion(self, validator):
        """Test that string values are properly converted to correct types."""
        params = {"temperature": "1.5"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 1.5}
        assert isinstance(normalized["temperature"], float)
        assert errors == []

    def test_normalization_excludes_invalid_parameters(self, validator):
        """Test that invalid parameters are excluded from normalized output."""
        params = {
            "temperature": "0.5",  # valid
            "reasoning_effort": "invalid",  # invalid
        }
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.5}
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]

    def test_normalization_empty_input(self, validator):
        """Test normalization with empty parameter dict."""
        params = {}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert errors == []

    # ========================================================================
    # Error Handling and Logging Tests
    # ========================================================================

    def test_validation_error_logging(self, validator, caplog):
        """Test that validation errors are logged."""
        params = {"temperature": "5.0"}

        with caplog.at_level(logging.ERROR):
            normalized, errors = validator.validate_and_normalize(params)

        assert "Invalid URI parameter value" in caplog.text
        assert "temperature=5.0" in caplog.text

    def test_multiple_validation_errors(self, validator):
        """Test handling of multiple validation errors."""
        params = {
            "temperature": "5.0",  # out of range
            "reasoning_effort": "invalid",  # invalid value
        }
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {}
        assert len(errors) == 2
        assert any("temperature" in err for err in errors)
        assert any("reasoning_effort" in err for err in errors)

    def test_error_messages_descriptive(self, validator):
        """Test that error messages are descriptive and helpful."""
        params = {"temperature": "3.0"}
        normalized, errors = validator.validate_and_normalize(params)

        assert len(errors) == 1
        error_msg = errors[0]
        assert "temperature" in error_msg
        assert "3.0" in error_msg
        assert "maximum" in error_msg.lower()

    # ========================================================================
    # Edge Cases and Special Values
    # ========================================================================

    def test_temperature_zero(self, validator):
        """Test temperature validation with zero value."""
        params = {"temperature": "0"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.0}
        assert errors == []

    def test_temperature_scientific_notation(self, validator):
        """Test temperature validation with scientific notation."""
        params = {"temperature": "1e-1"}  # 0.1
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.1}
        assert errors == []

    def test_parameter_order_preserved(self, validator):
        """Test that parameter order doesn't affect validation."""
        params1 = {"temperature": "0.5", "reasoning_effort": "high"}
        params2 = {"reasoning_effort": "high", "temperature": "0.5"}

        normalized1, errors1 = validator.validate_and_normalize(params1)
        normalized2, errors2 = validator.validate_and_normalize(params2)

        assert normalized1 == normalized2
        assert errors1 == errors2

    def test_duplicate_parameter_handling(self, validator):
        """Test handling when parameter appears multiple times (last value wins in dict)."""
        # Note: In actual URI parsing, parse_qs would handle this,
        # but validator receives a dict, so this tests dict behavior
        params = {"temperature": "0.8"}  # Only one value in dict
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.8}
        assert errors == []

    # ========================================================================
    # Integration-like Tests
    # ========================================================================

    def test_realistic_uri_parameters(self, validator):
        """Test validation with realistic URI parameter combinations."""
        params = {"temperature": "0.7", "reasoning_effort": "medium"}
        normalized, errors = validator.validate_and_normalize(params)

        assert normalized == {"temperature": 0.7, "reasoning_effort": "medium"}
        assert errors == []

    def test_partial_validation_success(self, validator):
        """Test that valid parameters are normalized even when others fail."""
        params = {
            "temperature": "0.5",  # valid
            "reasoning_effort": "invalid",  # invalid
            "unknown": "value",  # unknown
        }
        normalized, errors = validator.validate_and_normalize(params)

        # Only valid parameter should be in normalized output
        assert normalized == {"temperature": 0.5}
        # Only invalid parameter should generate error (unknown generates warning)
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]
