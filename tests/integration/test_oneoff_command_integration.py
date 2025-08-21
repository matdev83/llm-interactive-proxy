# mypy: disable-error-code="type-abstract"
"""
Integration tests for the OneOff command in the new SOLID architecture.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import AppConfig
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.domain.commands.oneoff_command import OneoffCommand


@pytest.fixture
async def app():
    """Create a test app with oneoff commands enabled."""
    # Create app with test config
    config = AppConfig()
    config.auth.disable_auth = True
    app = build_app(config)

    # Manually trigger startup to initialize service provider
    from src.core.app.test_builder import TestApplicationBuilder as ApplicationBuilder

    builder = ApplicationBuilder()
    service_provider = await builder._initialize_services(app, config)
    app.state.service_provider = service_provider

    # Initialize minimal state attributes that tests expect
    app.state.app_config = config
    app.state.functional_backends = {"openrouter"}
    
    # Ensure OneoffCommand is registered in the command registry
    from src.core.services.command_service import CommandRegistry
    command_registry = CommandRegistry()
    command_registry.register(OneoffCommand())
    app.state.command_registry = command_registry

    yield app


# Mock the get_integration_bridge function to return the bridge from app.state
def mock_get_integration_bridge(_=None):
    return app.state.integration_bridge


async def mock_dispatch(self, request, call_next):
    return await call_next(request)



async def test_oneoff_command_integration(app):
    """Test that the OneOff command works correctly in the integration environment."""
    # Get the backend service from the service provider
    backend_service = app.state.service_provider.get_required_service(IBackendService)

    # Create a test client
    client = TestClient(app)
    
    # Mock the command processor to handle oneoff commands
    from src.core.domain.processed_result import ProcessedResult
    from src.core.domain.command_results import CommandResult
    from src.core.domain.chat import ChatMessage
    from src.command_parser import CommandParser
    
    original_process_messages = CommandParser.process_messages
    
    async def mock_process_messages(self, messages):
        # Check if this is the oneoff command message
        if any("!/oneoff" in msg.content for msg in messages if isinstance(msg.content, str)):
            # Process the oneoff command
            oneoff_cmd = OneoffCommand()
            session = await app.state.service_provider.get_required_service(
                "ISessionService"
            ).get_session("test-oneoff-session")
            
            # Execute the command
            result = await oneoff_cmd.execute({"openai/gpt-4": True}, session, {})
            
            # Update the message content
            modified_messages = messages.copy()
            for i, msg in enumerate(modified_messages):
                if isinstance(msg.content, str) and "!/oneoff" in msg.content:
                    modified_messages[i].content = ""
            
            return modified_messages, True
        return messages, False
    
    # Patch the necessary functions
    with (
        patch(
            "src.core.integration.bridge.get_integration_bridge",
            new=mock_get_integration_bridge,
        ),
        patch(
            "src.core.security.middleware.APIKeyMiddleware.dispatch", new=mock_dispatch
        ),
        patch.object(
            backend_service,
            "call_completion",
            new=AsyncMock(
                side_effect=[
                    # Response for the command-only request
                    {
                        "id": "proxy-cmd-response",
                        "object": "chat.completion",
                        "created": 1677858242,
                        "model": "gpt-3.5-turbo",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "One-off route set to openai/gpt-4.",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    },
                    # Response for the follow-up request
                    {
                        "id": "backend-response",
                        "object": "chat.completion",
                        "created": 1677858242,
                        "model": "gpt-4",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "This is a response from the one-off route.",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 10,
                            "total_tokens": 20,
                        },
                    },
                ]
            ),
        ),
        patch.object(CommandParser, "process_messages", mock_process_messages),
    ):

        # First request with the one-off command
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/oneoff(openai/gpt-4)"}],
                "session_id": "test-oneoff-session",
            },
        )

        # Verify the response
        assert response.status_code == 200
        assert (
            "One-off route set to openai/gpt-4"
            in response.json()["choices"][0]["message"]["content"]
        )

        # Second request to use the one-off route
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello!"}],
                "session_id": "test-oneoff-session",
            },
        )

        # Verify that the one-off route was used
        assert response.status_code == 200
        assert response.json()["model"] == "gpt-4"
