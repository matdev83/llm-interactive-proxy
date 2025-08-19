"""
Integration tests for the PWD command in the new SOLID architecture.
"""

import pytest
from src.core.app.test_builder import build_test_app as build_app


@pytest.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    """Create a test application."""
    # Build the app
    app = build_app()

    # Manually set up services for testing since lifespan isn't called in tests
    from src.core.app.test_builder import TestApplicationBuilder as ApplicationBuilder
    from src.core.config.app_config import AppConfig, BackendConfig
    from src.core.di.services import set_service_provider

    # Ensure config exists
    app_config = AppConfig()
    app_config.auth.disable_auth = True

    # Configure backends with test API keys
    app_config.backends.openai = BackendConfig(api_key=["test-openai-key"])
    app_config.backends.openrouter = BackendConfig(api_key=["test-openrouter-key"])
    app_config.backends.anthropic = BackendConfig(api_key=["test-anthropic-key"])
    app_config.backends.gemini = BackendConfig(api_key=["test-gemini-key"])

    # Store minimal config in app.state
    app.state.app_config = app_config

    # The httpx client should be managed by the DI container, not directly in app.state

    # Create service provider using ApplicationBuilder's method
    builder = ApplicationBuilder()
    service_provider = await builder._initialize_services(app, app_config)

    # Store the service provider
    set_service_provider(service_provider)
    app.state.service_provider = service_provider

    # Initialize the integration bridge
    from src.core.integration.bridge import IntegrationBridge

    bridge = IntegrationBridge(app)
    bridge.new_initialized = True  # Mark new architecture as initialized
    app.state.integration_bridge = bridge

    # Mock the backend service to avoid actual API calls

    # We'll create a custom mock backend service that actually executes the pwd command
    class CustomMockBackendService:
        async def call_completion(self, request, stream=False):
            # Extract the session ID from the request
            session_id = getattr(request, "session_id", None)

            # Default response
            response_content = "This is a test response"

            # Check if this is the pwd command test
            if session_id == "test-pwd-session":
                # Get the content of the first message
                messages = getattr(request, "messages", [])
                if messages and len(messages) > 0:
                    message_content = (
                        messages[0].content
                        if hasattr(messages[0], "content")
                        else messages[0].get("content", "")
                    )
                    if message_content == "!/pwd":
                        # Actually execute the pwd command
                        from src.core.domain.commands.pwd_command import PwdCommand
                        from src.core.domain.session import Session, SessionState

                        # Create a session based on the test scenario
                        if (
                            hasattr(app, "_test_with_project_dir")
                            and app._test_with_project_dir
                        ):
                            session = Session(
                                session_id="test-pwd-session",
                                state=SessionState(project_dir="/test/project/dir"),
                            )
                        else:
                            session = Session(
                                session_id="test-pwd-session",
                                state=SessionState(project_dir=None),
                            )

                        # Execute the command
                        pwd_command = PwdCommand()
                        result = await pwd_command.execute({}, session)
                        response_content = result.message

            # Return the appropriate response
            return {
                "id": "test-response-id",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_content},
                        "finish_reason": "stop",
                    }
                ],
            }

    # Create a mock backend service
    mock_backend_service = CustomMockBackendService()

    # We need to patch the get_service and get_required_service methods
    from src.core.interfaces.backend_service_interface import IBackendService

    # Save the original methods
    original_get_service = service_provider.get_service
    original_get_required_service = service_provider.get_required_service

    # Create wrapper methods that return our mock for IBackendService
    def patched_get_service(service_type):
        if service_type == IBackendService:
            return mock_backend_service
        return original_get_service(service_type)

    def patched_get_required_service(service_type):
        if service_type == IBackendService:
            return mock_backend_service
        return original_get_required_service(service_type)

    # Apply the patches
    monkeypatch.setattr(service_provider, "get_service", patched_get_service)
    monkeypatch.setattr(
        service_provider, "get_required_service", patched_get_required_service
    )

    return app


async def test_pwd_command_integration_with_project_dir(app):
    """Test that the PWD command works correctly with a project directory set."""
    # Import the command and session classes
    from src.core.domain.commands.pwd_command import PwdCommand
    from src.core.domain.session import Session, SessionState

    # Create a session with a project directory
    session = Session(
        session_id="test-pwd-session",
        state=SessionState(project_dir="/test/project/dir"),
    )

    # Create the command
    pwd_command = PwdCommand()

    # Execute the command
    result = await pwd_command.execute({}, session)

    # Verify the result
    assert result.success is True
    assert result.message == "/test/project/dir"


async def test_pwd_command_integration_without_project_dir(app):
    """Test that the PWD command works correctly without a project directory set."""
    # Import the command and session classes
    from src.core.domain.commands.pwd_command import PwdCommand
    from src.core.domain.session import Session, SessionState

    # Create a session without a project directory
    session = Session(
        session_id="test-pwd-session",
        state=SessionState(project_dir=None),
    )

    # Create the command
    pwd_command = PwdCommand()

    # Execute the command
    result = await pwd_command.execute({}, session)

    # Verify the result
    assert result.success is True
    assert result.message == "Project directory not set"
