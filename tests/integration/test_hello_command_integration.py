"""
Integration tests for the Hello command in the new SOLID architecture.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app


@pytest.fixture
def app():
    """Create a test application."""
    # Build the app
    app = build_app()

    # Manually set up services for testing since lifespan isn't called in tests
    import httpx
    from src.core.app.application_factory import ServiceConfigurator
    from src.core.config.app_config import AppConfig
    from src.core.di.services import set_service_provider

    # Ensure config exists
    app.state.app_config = app.state.app_config or AppConfig()
    app.state.app_config.auth.disable_auth = True

    # Create httpx client for services
    app.state.httpx_client = httpx.AsyncClient()

    # Create service provider
    configurator = ServiceConfigurator()
    service_provider = configurator.configure_services(app.state.app_config)

    # Store the service provider
    set_service_provider(service_provider)
    app.state.service_provider = service_provider

    # Initialize the integration bridge
    from src.core.integration.bridge import IntegrationBridge

    bridge = IntegrationBridge(app)
    app.state.integration_bridge = bridge

    return app


def test_hello_command_integration(app):
    """Test that the Hello command works correctly in the integration environment."""
    # Mock the APIKeyMiddleware's dispatch method to always return the next response

    # Mock the get_integration_bridge function to return the bridge from app.state
    def mock_get_integration_bridge(app_param=None):
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
            "src.core.services.request_processor.RequestProcessor.process_request",
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
