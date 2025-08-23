"""Test file to verify validation constants are accessible and correctly imported."""

import pytest
from src.core.constants import (
    # Configuration validation error messages
    API_URL_MUST_START_WITH_HTTP_MESSAGE,
    BACKEND_MUST_BE_STRING_MESSAGE,
    BACKEND_NOT_FUNCTIONAL_MESSAGE,
    BACKEND_NOT_SUPPORTED_MESSAGE,
    # Specific validation error messages
    COMMAND_PREFIX_MUST_BE_AT_LEAST_CHARS_MESSAGE,
    COMMAND_PREFIX_MUST_BE_NON_EMPTY_STRING_MESSAGE,
    COMMAND_PREFIX_MUST_CONTAIN_PRINTABLE_CHARS_MESSAGE,
    COMMAND_PREFIX_MUST_NOT_EXCEED_CHARS_MESSAGE,
    MODEL_BACKEND_NOT_SUPPORTED_MESSAGE,
    MODEL_MUST_BE_STRING_MESSAGE,
    MODEL_UNSET_MESSAGE,
    OPENAI_URL_MUST_BE_STRING_MESSAGE,
    OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE,
    PROJECT_NAME_MUST_BE_SPECIFIED_MESSAGE,
    TEMPERATURE_MUST_BE_BETWEEN_MESSAGE,
    TEMPERATURE_OUT_OF_RANGE_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_MUST_BE_AT_LEAST_TWO_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE,
    TOOL_LOOP_MAX_REPEATS_REQUIRED_MESSAGE,
    TOOL_LOOP_MODE_INVALID_MESSAGE,
    TOOL_LOOP_MODE_REQUIRED_MESSAGE,
    TOOL_LOOP_TTL_MUST_BE_AT_LEAST_ONE_MESSAGE,
    TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE,
    TOOL_LOOP_TTL_REQUIRED_MESSAGE,
    VALIDATION_CANNOT_BE_EMPTY_MESSAGE,
    VALIDATION_INVALID_FORMAT_MESSAGE,
    VALIDATION_MUST_BE_AT_LEAST_MESSAGE,
    VALIDATION_MUST_BE_BETWEEN_MESSAGE,
    VALIDATION_MUST_BE_BOOLEAN_MESSAGE,
    VALIDATION_MUST_BE_INTEGER_MESSAGE,
    VALIDATION_MUST_BE_NUMBER_MESSAGE,
    VALIDATION_MUST_BE_POSITIVE_MESSAGE,
    VALIDATION_MUST_BE_SPECIFIED_MESSAGE,
    # Generic validation error messages
    VALIDATION_MUST_BE_STRING_MESSAGE,
    VALIDATION_NOT_SUPPORTED_MESSAGE,
)


def test_generic_validation_constants():
    """Test that generic validation constants have expected values."""
    assert VALIDATION_MUST_BE_STRING_MESSAGE == "{field} value must be a string"
    assert VALIDATION_MUST_BE_NUMBER_MESSAGE == "{field} must be a valid number"
    assert VALIDATION_MUST_BE_BOOLEAN_MESSAGE == "Boolean value must be specified"
    assert VALIDATION_MUST_BE_INTEGER_MESSAGE == "Invalid {field} value: {value}. Must be an integer."
    assert VALIDATION_MUST_BE_POSITIVE_MESSAGE == "{field} must be positive"
    assert VALIDATION_MUST_BE_AT_LEAST_MESSAGE == "{field} must be at least {min_value}"
    assert VALIDATION_MUST_BE_BETWEEN_MESSAGE == "{field} must be between {min_value} and {max_value}"
    assert VALIDATION_CANNOT_BE_EMPTY_MESSAGE == "{field} cannot be empty"
    assert VALIDATION_MUST_BE_SPECIFIED_MESSAGE == "{field} must be specified"
    assert VALIDATION_INVALID_FORMAT_MESSAGE == "Invalid {field} format: {value}"
    assert VALIDATION_NOT_SUPPORTED_MESSAGE == "{field} {value} not supported"


def test_specific_validation_constants():
    """Test that specific validation constants have expected values."""
    # Command prefix validation messages
    assert COMMAND_PREFIX_MUST_BE_AT_LEAST_CHARS_MESSAGE == "command prefix must be at least {min_chars} characters"
    assert COMMAND_PREFIX_MUST_NOT_EXCEED_CHARS_MESSAGE == "command prefix must not exceed {max_chars} characters"
    assert COMMAND_PREFIX_MUST_CONTAIN_PRINTABLE_CHARS_MESSAGE == "command prefix must contain only printable characters"
    assert COMMAND_PREFIX_MUST_BE_NON_EMPTY_STRING_MESSAGE == "command prefix must be a non-empty string"
    
    # Temperature validation messages
    assert TEMPERATURE_MUST_BE_BETWEEN_MESSAGE == "Temperature must be between {min_temp} and {max_temp}"
    assert TEMPERATURE_OUT_OF_RANGE_MESSAGE == "Temperature must be between 0.0 and 1.0"
    
    # Project validation messages
    assert PROJECT_NAME_MUST_BE_SPECIFIED_MESSAGE == "Project name must be specified"
    
    # Backend validation messages
    assert BACKEND_MUST_BE_STRING_MESSAGE == "Backend value must be a string"
    assert BACKEND_NOT_SUPPORTED_MESSAGE == "Backend {backend} not supported"
    assert BACKEND_NOT_FUNCTIONAL_MESSAGE == "Backend {backend} not functional (session override unset)"
    
    # Model validation messages
    assert MODEL_MUST_BE_STRING_MESSAGE == "Model value must be a string"
    assert MODEL_BACKEND_NOT_SUPPORTED_MESSAGE == "Backend {backend} in model {model} not supported"
    assert MODEL_UNSET_MESSAGE == "model unset"
    
    # OpenAI URL validation messages
    assert OPENAI_URL_MUST_BE_STRING_MESSAGE == "OpenAI URL value must be a string"
    assert OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE == "OpenAI URL must start with http:// or https://"
    
    # Tool loop validation messages
    assert TOOL_LOOP_MAX_REPEATS_MUST_BE_AT_LEAST_TWO_MESSAGE == "Max repeats must be at least 2"
    assert TOOL_LOOP_MAX_REPEATS_REQUIRED_MESSAGE == "Max repeats value must be specified"
    assert TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE == "Invalid max repeats value: {value}. Must be an integer."
    
    assert TOOL_LOOP_TTL_MUST_BE_AT_LEAST_ONE_MESSAGE == "TTL must be at least 1 second"
    assert TOOL_LOOP_TTL_REQUIRED_MESSAGE == "TTL value must be specified"
    assert TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE == "Invalid TTL value: {value}. Must be an integer."
    
    assert TOOL_LOOP_MODE_REQUIRED_MESSAGE == "Loop mode must be specified"
    assert TOOL_LOOP_MODE_INVALID_MESSAGE == "Invalid loop mode: {value}. Use break or chance_then_break."
    
    # Configuration validation messages
    assert API_URL_MUST_START_WITH_HTTP_MESSAGE == "API URL must start with http:// or https://"


def test_validation_constant_formatting():
    """Test that validation constants can be formatted correctly."""
    # Test generic validation message formatting
    formatted_string = VALIDATION_MUST_BE_STRING_MESSAGE.format(field="test")
    assert formatted_string == "test value must be a string"
    
    formatted_number = VALIDATION_MUST_BE_NUMBER_MESSAGE.format(field="temperature")
    assert formatted_number == "temperature must be a valid number"
    
    formatted_boolean = VALIDATION_MUST_BE_BOOLEAN_MESSAGE
    assert formatted_boolean == "Boolean value must be specified"
    
    formatted_integer = TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE.format(value="abc")
    assert formatted_integer == "Invalid max repeats value: abc. Must be an integer."
    
    formatted_positive = VALIDATION_MUST_BE_POSITIVE_MESSAGE.format(field="ttl")
    assert formatted_positive == "ttl must be positive"
    
    formatted_at_least = VALIDATION_MUST_BE_AT_LEAST_MESSAGE.format(field="repeats", min_value=2)
    assert formatted_at_least == "repeats must be at least 2"
    
    formatted_between = VALIDATION_MUST_BE_BETWEEN_MESSAGE.format(field="temperature", min_value=0.0, max_value=1.0)
    assert formatted_between == "temperature must be between 0.0 and 1.0"
    
    formatted_empty = VALIDATION_CANNOT_BE_EMPTY_MESSAGE.format(field="project_name")
    assert formatted_empty == "project_name cannot be empty"
    
    formatted_specified = VALIDATION_MUST_BE_SPECIFIED_MESSAGE.format(field="model")
    assert formatted_specified == "model must be specified"
    
    formatted_format = VALIDATION_INVALID_FORMAT_MESSAGE.format(field="url", value="invalid_url")
    assert formatted_format == "Invalid url format: invalid_url"
    
    formatted_not_supported = VALIDATION_NOT_SUPPORTED_MESSAGE.format(field="backend", value="invalid_backend")
    assert formatted_not_supported == "backend invalid_backend not supported"
    
    # Test specific validation message formatting
    formatted_backend_not_supported = BACKEND_NOT_SUPPORTED_MESSAGE.format(backend="invalid_backend")
    assert formatted_backend_not_supported == "Backend invalid_backend not supported"
    
    formatted_model_backend_not_supported = MODEL_BACKEND_NOT_SUPPORTED_MESSAGE.format(backend="invalid_backend", model="test:model")
    assert formatted_model_backend_not_supported == "Backend invalid_backend in model test:model not supported"
    
    formatted_temperature_between = TEMPERATURE_MUST_BE_BETWEEN_MESSAGE.format(min_temp=0.0, max_temp=2.0)
    assert formatted_temperature_between == "Temperature must be between 0.0 and 2.0"
    
    formatted_max_repeats_integer = TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE.format(value="not_a_number")
    assert formatted_max_repeats_integer == "Invalid max repeats value: not_a_number. Must be an integer."
    
    formatted_ttl_integer = TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE.format(value="not_a_number")
    assert formatted_ttl_integer == "Invalid TTL value: not_a_number. Must be an integer."
    
    formatted_mode_invalid = TOOL_LOOP_MODE_INVALID_MESSAGE.format(value="invalid_mode")
    assert formatted_mode_invalid == "Invalid loop mode: invalid_mode. Use break or chance_then_break."


if __name__ == "__main__":
    pytest.main([__file__])