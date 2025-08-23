"""Test fixtures for unit tests."""

# Import session fixtures
# Import backend fixtures
from tests.unit.fixtures.backend_fixtures import (
    backend_config,
    backend_service,
    httpx_client,
    mock_backend,
    mock_backend_factory,
    mock_config,
    mock_rate_limiter,
    mock_session_service,
    session_with_backend_config,
)
from tests.unit.fixtures.command_fixtures import (
    command_parser_config,
    mock_app,
    process_command,
    session_with_hello,
    session_with_model,
    session_with_project,
)

# Import command fixtures
from tests.unit.fixtures.command_fixtures import (
    command_parser_from_app_with_commands as command_parser,
)

# Import multimodal fixtures
from tests.unit.fixtures.multimodal_fixtures import (
    image_content_part,
    image_message,
    message_with_command,
    multimodal_message,
    multimodal_message_with_command,
    text_content_part,
    text_message,
)

__all__ = [
    "backend_config",
    "backend_service",
    "command_parser",  # This will now refer to the aliased command_parser_from_app_with_commands
    "command_parser_config",
    "httpx_client",
    "image_content_part",
    "image_message",
    "message_with_command",
    "mock_app",
    "mock_backend",
    "mock_backend_factory",
    "mock_config",
    "mock_rate_limiter",
    "mock_session_service",
    "multimodal_message",
    "multimodal_message_with_command",
    "process_command",
    "session_with_backend_config",
    "session_with_hello",
    "session_with_model",
    "session_with_project",
    "test_command_registry",
    "test_mock_app",
    "test_session",
    "test_session_id",
    "test_session_state",
    "test_session_with_hello",
    "test_session_with_model",
    "test_session_with_project",
    "text_content_part",
    "text_message",
]
