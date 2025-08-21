"""Test file to verify error constants are accessible and correctly imported."""

import pytest

from src.core.constants import (
    # Authentication error messages
    AUTH_INVALID_OR_MISSING_API_KEY,
    AUTH_INVALID_OR_MISSING_AUTH_TOKEN,
    
    # Backend error messages
    BACKEND_NOT_FOUND_ERROR,
    BACKEND_CONNECTION_ERROR,
    
    # Command error messages
    COMMAND_NOT_FOUND_ERROR,
    COMMAND_EXECUTION_ERROR,
    
    # Configuration error messages
    CONFIG_LOADING_ERROR,
    CONFIG_VALIDATION_ERROR,
    
    # Session error messages
    SESSION_NOT_FOUND_ERROR,
    
    # Model error messages
    MODEL_NOT_AVAILABLE_ERROR,
    
    # Loop detection error messages
    LOOP_DETECTED_ERROR,
    
    # Tool call error messages
    TOOL_CALL_EXECUTION_ERROR,
    
    # Streaming error messages
    STREAMING_PROCESSING_ERROR,
    
    # Network error messages
    NETWORK_TIMEOUT_ERROR,
    
    # File system error messages
    FILE_NOT_FOUND_ERROR,
    
    # JSON error messages
    JSON_PARSING_ERROR,
    
    # Validation error messages
    VALIDATION_TYPE_ERROR,
    
    # Rate limiting error messages
    RATE_LIMIT_EXCEEDED_ERROR,
    
    # Security error messages
    SECURITY_REDACTION_ERROR,
    
    # Generic error messages
    GENERIC_INTERNAL_ERROR,
)


def test_authentication_error_constants():
    """Test that authentication error constants have expected values."""
    assert AUTH_INVALID_OR_MISSING_API_KEY == "Invalid or missing API key"
    assert AUTH_INVALID_OR_MISSING_AUTH_TOKEN == "Invalid or missing auth token"


def test_backend_error_constants():
    """Test that backend error constants have expected format."""
    assert BACKEND_NOT_FOUND_ERROR == "Backend {backend} not found"
    assert BACKEND_CONNECTION_ERROR == "Connection error to backend: {error}"
    
    # Test formatting
    formatted_backend = BACKEND_NOT_FOUND_ERROR.format(backend="openai")
    assert formatted_backend == "Backend openai not found"
    
    formatted_connection = BACKEND_CONNECTION_ERROR.format(error="timeout")
    assert formatted_connection == "Connection error to backend: timeout"


def test_command_error_constants():
    """Test that command error constants have expected format."""
    assert COMMAND_NOT_FOUND_ERROR == "Command not found: {command}"
    assert COMMAND_EXECUTION_ERROR == "Error executing command: {error}"
    
    # Test formatting
    formatted_not_found = COMMAND_NOT_FOUND_ERROR.format(command="set")
    assert formatted_not_found == "Command not found: set"
    
    formatted_execution = COMMAND_EXECUTION_ERROR.format(error="invalid argument")
    assert formatted_execution == "Error executing command: invalid argument"


def test_configuration_error_constants():
    """Test that configuration error constants have expected format."""
    assert CONFIG_LOADING_ERROR == "Error loading configuration: {error}"
    assert CONFIG_VALIDATION_ERROR == "Configuration validation error: {error}"


def test_session_error_constants():
    """Test that session error constants have expected format."""
    assert SESSION_NOT_FOUND_ERROR == "Session not found: {session_id}"
    
    # Test formatting
    formatted_session = SESSION_NOT_FOUND_ERROR.format(session_id="test-123")
    assert formatted_session == "Session not found: test-123"


def test_model_error_constants():
    """Test that model error constants have expected format."""
    assert MODEL_NOT_AVAILABLE_ERROR == "Model not available: {model}"
    
    # Test formatting
    formatted_model = MODEL_NOT_AVAILABLE_ERROR.format(model="gpt-4")
    assert formatted_model == "Model not available: gpt-4"


def test_loop_detection_error_constants():
    """Test that loop detection error constants have expected values."""
    assert LOOP_DETECTED_ERROR == "Loop detected in response stream"


def test_tool_call_error_constants():
    """Test that tool call error constants have expected format."""
    assert TOOL_CALL_EXECUTION_ERROR == "Error executing tool call: {error}"
    
    # Test formatting
    formatted_tool = TOOL_CALL_EXECUTION_ERROR.format(error="timeout")
    assert formatted_tool == "Error executing tool call: timeout"


def test_streaming_error_constants():
    """Test that streaming error constants have expected format."""
    assert STREAMING_PROCESSING_ERROR == "Error processing streaming response: {error}"
    
    # Test formatting
    formatted_streaming = STREAMING_PROCESSING_ERROR.format(error="malformed chunk")
    assert formatted_streaming == "Error processing streaming response: malformed chunk"


def test_network_error_constants():
    """Test that network error constants have expected format."""
    assert NETWORK_TIMEOUT_ERROR == "Network timeout: {error}"
    
    # Test formatting
    formatted_network = NETWORK_TIMEOUT_ERROR.format(error="connection lost")
    assert formatted_network == "Network timeout: connection lost"


def test_file_system_error_constants():
    """Test that file system error constants have expected format."""
    assert FILE_NOT_FOUND_ERROR == "File not found: {file_path}"
    
    # Test formatting
    formatted_file = FILE_NOT_FOUND_ERROR.format(file_path="/tmp/test.txt")
    assert formatted_file == "File not found: /tmp/test.txt"


def test_json_error_constants():
    """Test that JSON error constants have expected format."""
    assert JSON_PARSING_ERROR == "JSON parsing error: {error}"
    
    # Test formatting
    formatted_json = JSON_PARSING_ERROR.format(error="unexpected token")
    assert formatted_json == "JSON parsing error: unexpected token"


def test_validation_error_constants():
    """Test that validation error constants have expected format."""
    assert VALIDATION_TYPE_ERROR == "Type validation error: expected {expected_type}, got {actual_type}"
    
    # Test formatting
    formatted_validation = VALIDATION_TYPE_ERROR.format(expected_type="string", actual_type="int")
    assert formatted_validation == "Type validation error: expected string, got int"


def test_rate_limiting_error_constants():
    """Test that rate limiting error constants have expected format."""
    assert RATE_LIMIT_EXCEEDED_ERROR == "Rate limit exceeded: {limit}"
    
    # Test formatting
    formatted_rate = RATE_LIMIT_EXCEEDED_ERROR.format(limit="100 requests/minute")
    assert formatted_rate == "Rate limit exceeded: 100 requests/minute"


def test_security_error_constants():
    """Test that security error constants have expected format."""
    assert SECURITY_REDACTION_ERROR == "Error redacting sensitive data: {error}"
    
    # Test formatting
    formatted_security = SECURITY_REDACTION_ERROR.format(error="invalid regex")
    assert formatted_security == "Error redacting sensitive data: invalid regex"


def test_generic_error_constants():
    """Test that generic error constants have expected format."""
    assert GENERIC_INTERNAL_ERROR == "Internal server error: {error}"
    
    # Test formatting
    formatted_generic = GENERIC_INTERNAL_ERROR.format(error="database connection failed")
    assert formatted_generic == "Internal server error: database connection failed"


if __name__ == "__main__":
    pytest.main([__file__])