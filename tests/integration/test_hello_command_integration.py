"""
Integration tests for the Hello command in the new SOLID architecture.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
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
        from fastapi.responses import JSONResponse

        # Check if this is a Hello command
        messages = request_data.messages
        if messages and messages[0]["content"].startswith("!/hello"):
            return JSONResponse(
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
                }
            )

        # Default response
        return JSONResponse(
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
            }
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
        )

        # Verify the response
        assert response.status_code == 200
        assert (
            "Welcome to LLM Interactive Proxy"
            in response.json()["choices"][0]["message"]["content"]
        )
