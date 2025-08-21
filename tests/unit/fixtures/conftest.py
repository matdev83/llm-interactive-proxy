"""Pytest configuration for fixtures.

This module makes the fixtures available to pytest.
"""

# Import all fixtures
from tests.unit.fixtures import (
    # Session fixtures
    test_session_id,
    test_session,
    test_session_state,
    test_session_with_model,
    test_session_with_project,
    test_session_with_hello,
    test_mock_app,
    test_command_registry,
    
    # Command fixtures
    mock_app,
    command_parser_config,
    command_parser,
    process_command,
    session_with_model,
    session_with_project,
    session_with_hello,
    
    # Backend fixtures
    mock_backend_factory,
    mock_backend,
    httpx_client,
    mock_rate_limiter,
    mock_config,
    mock_session_service,
    backend_service,
    backend_config,
    session_with_backend_config,
    
    # Multimodal fixtures
    text_content_part,
    image_content_part,
    multimodal_message,
    text_message,
    image_message,
    message_with_command,
    multimodal_message_with_command,
)

# No need to re-export fixtures - pytest will automatically discover them