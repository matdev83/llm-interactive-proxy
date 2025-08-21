"""
Integration tests for the Hello command in the new SOLID architecture.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
async def app(monkeypatch: pytest.MonkeyPatch):
    """Create a test application."""
    # Create test config with auth disabled from the start
    from src.core.app.test_builder import TestApplicationBuilder as ApplicationBuilder
    from src.core.config.app_config import AppConfig, BackendConfig
    from src.core.di.services import set_service_provider

    # Ensure config exists with auth disabled
    app_config = AppConfig()
    app_config.auth.disable_auth = True

    # Configure backends with test API keys
    app_config.backends.openai = BackendConfig(api_key=["test-openai-key"])
    app_config.backends.openrouter = BackendConfig(api_key=["test-openrouter-key"])
    app_config.backends.anthropic = BackendConfig(api_key=["test-anthropic-key"])
    app_config.backends.gemini = BackendConfig(api_key=["test-gemini-key"])

    # Build the app first
    from src.core.app.test_builder import build_test_app

    app = build_test_app(app_config)

    # Store minimal config in app.state
    app.state.app_config = app_config

    # The httpx client should be managed by the DI container, not directly in app.state

    # Use the staged approach to build services
    builder = ApplicationBuilder().add_test_stages()
    new_app = await builder.build(app_config)

    # Get the service provider from the new app
    service_provider = new_app.state.service_provider

    # Store the service provider
    set_service_provider(service_provider)
    app.state.service_provider = service_provider

    # Copy any other state that might be needed
    if hasattr(new_app.state, "httpx_client"):
        app.state.httpx_client = new_app.state.httpx_client

    # Initialize the integration bridge
    from src.core.integration.bridge import IntegrationBridge

    bridge = IntegrationBridge(app)
    bridge.new_initialized = True  # Mark new architecture as initialized
    app.state.integration_bridge = bridge

    # Mock the backend service to avoid actual API calls
    from unittest.mock import AsyncMock

    # Create a mock response as a dictionary
    mock_response = {
        "id": "test-response-id",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "This is a test response"},
                "finish_reason": "stop",
            }
        ],
    }

    # Create a mock backend service
    mock_backend_service = AsyncMock()
    mock_backend_service.call_completion.return_value = mock_response

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


def test_hello_command_integration(app):
    """Test that the Hello command works correctly in the integration environment."""
    # Mock the APIKeyMiddleware's dispatch method to always return the next response

    # Mock the get_integration_bridge function to return the bridge from app.state
    def mock_get_integration_bridge(_=None):
        return app.state.integration_bridge

    async def mock_dispatch(self, request, call_next):
        return await call_next(request)

    # Mock the process_request method to return a successful response
    async def mock_process_request(self, request, request_data):
        """Mock the process_request method to return a successful response."""
        from src.core.domain.responses import ResponseEnvelope

        # Check if this is a Hello command
        messages = request_data.messages
        if messages and len(messages) > 0:
            # Check the first message - accessing content attribute on ChatMessage object
            first_message_content = (
                messages[0].content if hasattr(messages[0], "content") else ""
            )

            if isinstance(
                first_message_content, str
            ) and first_message_content.startswith("!/hello"):
                return ResponseEnvelope(
                    content={
                        "id": "test-id",
                        "object": "chat.completion",
                        "created": 1677858242,
                        "model": request_data.model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "Welcome to LLM Interactive Proxy!\n\nAvailable commands:\n- !/help - Show help information\n- !/set(param=value) - Set a parameter value\n- !/unset(param) - Unset a parameter value",
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
                    headers={"content-type": "application/json"},
                    status_code=200,
                )

        # Default response
        return ResponseEnvelope(
            content={
                "id": "test-id",
                "object": "chat.completion",
                "created": 1677858242,
                "model": request_data.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Default response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
            headers={"content-type": "application/json"},
            status_code=200,
        )

    with (
        patch(
            "src.core.integration.bridge.get_integration_bridge",
            new=mock_get_integration_bridge,
        ),
        patch(
            "src.core.security.middleware.APIKeyMiddleware.dispatch", new=mock_dispatch
        ),
        patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            new=mock_process_request,
        ),
    ):

        # Create a test client
        client = TestClient(app)

        # Send a Hello command
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "!/hello"}],
                "session_id": "test-hello-session",
            },
            headers={"Authorization": "Bearer test-openai-key"},
        )

        # Verify the response
        assert response.status_code == 200
        assert (
            "Welcome to LLM Interactive Proxy"
            in response.json()["choices"][0]["message"]["content"]
        )
