"""Constants for validation error messages.

This module contains constants for common validation error messages to make tests
less fragile and more maintainable.
"""

# Generic validation error messages
VALIDATION_MUST_BE_STRING_MESSAGE = "{field} value must be a string"
VALIDATION_MUST_BE_NUMBER_MESSAGE = "{field} must be a valid number"
VALIDATION_MUST_BE_BOOLEAN_MESSAGE = "Boolean value must be specified"
VALIDATION_MUST_BE_INTEGER_MESSAGE = (
    "Invalid {field} value: {value}. Must be an integer."
)
VALIDATION_MUST_BE_POSITIVE_MESSAGE = "{field} must be positive"
VALIDATION_MUST_BE_AT_LEAST_MESSAGE = "{field} must be at least {min_value}"
VALIDATION_MUST_BE_BETWEEN_MESSAGE = (
    "{field} must be between {min_value} and {max_value}"
)
VALIDATION_CANNOT_BE_EMPTY_MESSAGE = "{field} cannot be empty"
VALIDATION_MUST_BE_SPECIFIED_MESSAGE = "{field} must be specified"
VALIDATION_INVALID_FORMAT_MESSAGE = "Invalid {field} format: {value}"
VALIDATION_NOT_SUPPORTED_MESSAGE = "{field} {value} not supported"

# Specific validation error messages
COMMAND_PREFIX_MUST_BE_AT_LEAST_CHARS_MESSAGE = (
    "command prefix must be at least {min_chars} characters"
)
COMMAND_PREFIX_MUST_NOT_EXCEED_CHARS_MESSAGE = (
    "command prefix must not exceed {max_chars} characters"
)
COMMAND_PREFIX_MUST_CONTAIN_PRINTABLE_CHARS_MESSAGE = (
    "command prefix must contain only printable characters"
)
COMMAND_PREFIX_MUST_BE_NON_EMPTY_STRING_MESSAGE = (
    "command prefix must be a non-empty string"
)

TEMPERATURE_MUST_BE_BETWEEN_MESSAGE = (
    "Temperature must be between {min_temp} and {max_temp}"
)
TEMPERATURE_OUT_OF_RANGE_MESSAGE = "Temperature must be between 0.0 and 1.0"

PROJECT_NAME_MUST_BE_SPECIFIED_MESSAGE = "Project name must be specified"

BACKEND_MUST_BE_STRING_MESSAGE = "Backend value must be a string"
BACKEND_NOT_SUPPORTED_MESSAGE = "Backend {backend} not supported"
BACKEND_NOT_FUNCTIONAL_MESSAGE = (
    "Backend {backend} not functional (session override unset)"
)

MODEL_MUST_BE_STRING_MESSAGE = "Model value must be a string"
MODEL_BACKEND_NOT_SUPPORTED_MESSAGE = "Backend {backend} in model {model} not supported"
MODEL_UNSET_MESSAGE = "model unset"

OPENAI_URL_MUST_BE_STRING_MESSAGE = "OpenAI URL value must be a string"
OPENAI_URL_MUST_START_WITH_HTTP_MESSAGE = (
    "OpenAI URL must start with http:// or https://"
)

TOOL_LOOP_MAX_REPEATS_MUST_BE_AT_LEAST_TWO_MESSAGE = "Max repeats must be at least 2"
TOOL_LOOP_MAX_REPEATS_REQUIRED_MESSAGE = "Max repeats value must be specified"
TOOL_LOOP_MAX_REPEATS_MUST_BE_INTEGER_MESSAGE = (
    "Invalid max repeats value: {value}. Must be an integer."
)

TOOL_LOOP_TTL_MUST_BE_AT_LEAST_ONE_MESSAGE = "TTL must be at least 1 second"
TOOL_LOOP_TTL_REQUIRED_MESSAGE = "TTL value must be specified"
TOOL_LOOP_TTL_MUST_BE_INTEGER_MESSAGE = (
    "Invalid TTL value: {value}. Must be an integer."
)

TOOL_LOOP_MODE_REQUIRED_MESSAGE = "Loop mode must be specified"
TOOL_LOOP_MODE_INVALID_MESSAGE = (
    "Invalid loop mode: {value}. Use break or chance_then_break."
)

# Configuration validation error messages
API_URL_MUST_START_WITH_HTTP_MESSAGE = "API URL must start with http:// or https://"
