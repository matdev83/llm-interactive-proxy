"""Tests for the versioned API endpoints."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app
from src.core.domain.chat import ChatResponse
from src.core.interfaces.backend_service import IBackendService


@pytest.fixture
def app():
    """Create a test app with the new architecture enabled."""
    # Set environment variables to use new services
    os.environ["USE_NEW_BACKEND_SERVICE"] = "true"
    os.environ["USE_NEW_SESSION_SERVICE"] = "true"
    os.environ["USE_NEW_COMMAND_SERVICE"] = "true"
    os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"

    app = build_app()

    # Import integration helpers and initialize

    # Set up app state
    if not hasattr(app.state, "config"):
        app.state.config = {
            "command_prefix": "!/",
            "proxy_timeout": 300,
            "api_keys": ["test-proxy-key"],
        }

    yield app

    # Clean up
    for key in [
        "USE_NEW_BACKEND_SERVICE",
        "USE_NEW_SESSION_SERVICE",
        "USE_NEW_COMMAND_SERVICE",
        "USE_NEW_REQUEST_PROCESSOR",
    ]:
        if key in os.environ:
            del os.environ[key]


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
async def initialized_app(app):
    """Create and initialize the app with services for testing."""
    # Initialize integration bridge
    import httpx
    from src.core.di.services import set_service_provider
    from src.core.integration import get_integration_bridge

    # Set up HTTP client if not present
    if not hasattr(app.state, "httpx_client"):
        app.state.httpx_client = httpx.AsyncClient()

    # Initialize integration bridge
    bridge = get_integration_bridge(app)
    await bridge.initialize_new_architecture()

    # The service provider is already set up by build_app
    # Just set it globally if needed
    if hasattr(app.state, "service_provider"):
        set_service_provider(app.state.service_provider)

    # Initialize new architecture
    await bridge.initialize_new_architecture()

    yield app


def test_versioned_endpoint_exists(client):
    """Test that the versioned endpoint exists."""
    # Should not return 404
    response = client.post(
        "/v2/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Test message"}],
        },
    )

    # We expect an error due to missing services, but not a 404
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_versioned_endpoint_with_backend_service(initialized_app):
    """Test that the versioned endpoint uses the backend service."""
    # Create a test client
    client = TestClient(initialized_app)

    # Mock the backend service
    service_provider = initialized_app.state.service_provider
    backend_service = service_provider.get_service(IBackendService)

    # Create a mock response
    mock_response = ChatResponse(
        id="test-response",
        created=1234567890,
        model="test-model",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop",
            }
        ],
    )

    # Patch the backend service
    with patch.object(
        backend_service, "call_completion", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = mock_response

        # Make a request to the versioned endpoint
        response = client.post(
            "/v2/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test message"}],
                "session_id": "test-session",
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-response"
        assert data["choices"][0]["message"]["content"] == "Test response"

        # Verify backend service was called
        mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_versioned_endpoint_with_commands(initialized_app):
    """Test that the versioned endpoint processes commands."""
    # Create a test client
    client = TestClient(initialized_app)

    # Make a request with a command
    response = client.post(
        "/v2/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "!/help"}],
            "session_id": "test-command-session",
        },
        headers={"Authorization": "Bearer test-proxy-key"},
    )

    # Check response
    assert response.status_code == 200
    data = response.json()

    # Should contain command result
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert "message" in data["choices"][0]
    assert "content" in data["choices"][0]["message"]

    # Command result should mention available commands
    content = data["choices"][0]["message"]["content"]
    assert "commands" in content.lower() or "help" in content.lower()


@pytest.mark.asyncio
async def test_compatibility_endpoint(initialized_app):
    """Test that the compatibility endpoint works."""
    # Create a test client
    client = TestClient(initialized_app)

    # Mock the backend service
    service_provider = initialized_app.state.service_provider
    backend_service = service_provider.get_service(IBackendService)

    # Create a mock response
    mock_response = ChatResponse(
        id="compat-response",
        created=1234567890,
        model="test-model",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Compatibility response"},
                "finish_reason": "stop",
            }
        ],
    )

    # Patch the backend service
    with patch.object(
        backend_service, "call_completion", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = mock_response

        # Set feature flag to use new services
        os.environ["USE_NEW_REQUEST_PROCESSOR"] = "true"

        try:
            # Make a request to the compatibility endpoint
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Test message"}],
                    "session_id": "test-compat-session",
                },
                headers={"Authorization": "Bearer test-proxy-key"},
            )

            # Check response
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "compat-response"
            assert data["choices"][0]["message"]["content"] == "Compatibility response"

        finally:
            # Clean up
            if "USE_NEW_REQUEST_PROCESSOR" in os.environ:
                del os.environ["USE_NEW_REQUEST_PROCESSOR"]
