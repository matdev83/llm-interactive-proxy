"""Constants for error messages.

This module contains constants for common error messages and exception texts
to make the test suite less fragile and more maintainable.
"""

# Authentication error messages
AUTH_INVALID_OR_MISSING_API_KEY = "Invalid or missing API key"
AUTH_INVALID_OR_MISSING_AUTH_TOKEN = "Invalid or missing auth token"
AUTH_BYPASS_PATH_MESSAGE = "Authentication bypassed for path: {path}"

# Backend error messages
BACKEND_NOT_FOUND_ERROR = "Backend {backend} not found"
BACKEND_CONFIGURATION_ERROR = "Error configuring backend: {error}"
BACKEND_CONNECTION_ERROR = "Connection error to backend: {error}"
BACKEND_RATE_LIMITED_ERROR = "Rate limited by backend: {backend}"
BACKEND_MODEL_NOT_SUPPORTED_ERROR = "Model {model} not supported by backend {backend}"
BACKEND_INVALID_RESPONSE_ERROR = "Invalid response from backend: {error}"
BACKEND_TIMEOUT_ERROR = "Timeout communicating with backend: {backend}"

# Command error messages
COMMAND_PARSING_ERROR = "Error parsing command: {error}"
COMMAND_EXECUTION_ERROR = "Error executing command: {error}"
COMMAND_NOT_FOUND_ERROR = "Command not found: {command}"
COMMAND_INVALID_ARGUMENT_ERROR = "Invalid argument for command {command}: {argument}"
COMMAND_MISSING_ARGUMENT_ERROR = "Missing required argument for command {command}: {argument}"
COMMAND_PERMISSION_DENIED_ERROR = "Permission denied for command: {command}"

# Configuration error messages
CONFIG_LOADING_ERROR = "Error loading configuration: {error}"
CONFIG_VALIDATION_ERROR = "Configuration validation error: {error}"
CONFIG_MISSING_REQUIRED_FIELD_ERROR = "Missing required configuration field: {field}"
CONFIG_INVALID_VALUE_ERROR = "Invalid configuration value for {field}: {value}"

# Session error messages
SESSION_NOT_FOUND_ERROR = "Session not found: {session_id}"
SESSION_CREATION_ERROR = "Error creating session: {error}"
SESSION_UPDATE_ERROR = "Error updating session: {error}"
SESSION_DELETION_ERROR = "Error deleting session: {error}"

# Model error messages
MODEL_DISCOVERY_ERROR = "Error discovering models: {error}"
MODEL_INVALID_FORMAT_ERROR = "Invalid model format: {model}"
MODEL_NOT_AVAILABLE_ERROR = "Model not available: {model}"

# Loop detection error messages
LOOP_DETECTION_ERROR = "Loop detection error: {error}"
LOOP_DETECTION_ENABLED_ERROR = "Error enabling loop detection: {error}"
LOOP_DETECTION_DISABLED_ERROR = "Error disabling loop detection: {error}"
LOOP_DETECTED_ERROR = "Loop detected in response stream"

# Tool call error messages
TOOL_CALL_EXECUTION_ERROR = "Error executing tool call: {error}"
TOOL_CALL_NOT_FOUND_ERROR = "Tool call not found: {tool_call_id}"
TOOL_CALL_INVALID_FORMAT_ERROR = "Invalid tool call format: {error}"
TOOL_CALL_MAX_RETRIES_EXCEEDED_ERROR = "Maximum tool call retries exceeded for: {tool_name}"

# Streaming error messages
STREAMING_CONNECTION_ERROR = "Streaming connection error: {error}"
STREAMING_PROCESSING_ERROR = "Error processing streaming response: {error}"
STREAMING_TIMEOUT_ERROR = "Streaming timeout: {error}"

# Network error messages
NETWORK_CONNECTION_ERROR = "Network connection error: {error}"
NETWORK_TIMEOUT_ERROR = "Network timeout: {error}"
NETWORK_DNS_ERROR = "DNS resolution error: {error}"

# File system error messages
FILE_NOT_FOUND_ERROR = "File not found: {file_path}"
FILE_PERMISSION_ERROR = "Permission denied accessing file: {file_path}"
FILE_READ_ERROR = "Error reading file: {file_path} - {error}"
FILE_WRITE_ERROR = "Error writing file: {file_path} - {error}"

# JSON error messages
JSON_PARSING_ERROR = "JSON parsing error: {error}"
JSON_ENCODING_ERROR = "JSON encoding error: {error}"

# Validation error messages
VALIDATION_TYPE_ERROR = "Type validation error: expected {expected_type}, got {actual_type}"
VALIDATION_RANGE_ERROR = "Value out of range: {value} not in [{min_value}, {max_value}]"
VALIDATION_REQUIRED_FIELD_ERROR = "Required field missing: {field}"
VALIDATION_FORMAT_ERROR = "Invalid format for {field}: {value}"

# Rate limiting error messages
RATE_LIMIT_EXCEEDED_ERROR = "Rate limit exceeded: {limit}"
RATE_LIMIT_WAIT_ERROR = "Error waiting for rate limit: {error}"

# Security error messages
SECURITY_REDACTION_ERROR = "Error redacting sensitive data: {error}"
SECURITY_VALIDATION_ERROR = "Security validation failed: {error}"

# Generic error messages
GENERIC_INTERNAL_ERROR = "Internal server error: {error}"
GENERIC_NOT_IMPLEMENTED_ERROR = "Not implemented: {feature}"
GENERIC_SERVICE_UNAVAILABLE_ERROR = "Service unavailable: {service}"