"""Tests for the updated hybrid controller without legacy fallbacks."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    app = FastAPI()
    app.state.config = {"command_prefix": "!/"}
    yield app


@pytest.fixture
def reset_bridge():
    """Reset the global bridge instance after the test."""
    import src.core.integration.bridge

    old_bridge = src.core.integration.bridge._bridge
    src.core.integration.bridge._bridge = None
    yield
    src.core.integration.bridge._bridge = old_bridge


@pytest.fixture
async def setup_app(app, reset_bridge):
    """Set up the app with necessary services for testing."""
    # Create mock services
    mock_request_processor = AsyncMock()
    mock_request_processor.process_request = AsyncMock(
        return_value=MagicMock(body=b'{"message": "processed"}')
    )

    # Set up service provider
    mock_provider = MagicMock()
    mock_provider.get_service.return_value = mock_request_processor
    mock_provider.get_required_service.return_value = mock_request_processor

    # Add service provider to app state
    app.state.service_provider = mock_provider

    # Add routes
    from src.core.integration.hybrid_controller import (
        hybrid_anthropic_messages,
        hybrid_chat_completions,
    )

    app.post("/v2/chat/completions")(hybrid_chat_completions)
    app.post("/v2/anthropic/messages")(hybrid_anthropic_messages)

    yield {
        "app": app,
        "mock_provider": mock_provider,
        "mock_request_processor": mock_request_processor,
    }


def test_get_service_provider_if_available(setup_app):
    """Test that get_service_provider_if_available returns the service provider."""
    from src.core.integration.hybrid_controller import get_service_provider_if_available

    # Create a test request
    test_request = MagicMock()
    test_request.app.state.service_provider = setup_app["mock_provider"]

    # Call the function
    import asyncio

    service_provider = asyncio.run(get_service_provider_if_available(test_request))

    # Verify the service provider is returned
    assert service_provider == setup_app["mock_provider"]


def test_get_service_provider_if_available_error(setup_app):
    """Test that get_service_provider_if_available handles errors properly."""
    from src.core.integration.hybrid_controller import get_service_provider_if_available

    # Create a test request
    test_request = MagicMock()
    del (
        test_request.app.state.service_provider
    )  # Remove the attribute to trigger AttributeError

    # Call the function
    import asyncio

    service_provider = asyncio.run(get_service_provider_if_available(test_request))

    # Verify None is returned
    assert service_provider is None


def test_hybrid_chat_completions(setup_app):
    """Test that hybrid_chat_completions uses the request processor correctly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the hybrid endpoint
    response = client.post(
        "/v2/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Test message"}],
        },
    )

    # Verify that the request was processed by the mock
    setup_app["mock_request_processor"].process_request.assert_called_once()

    # Check response
    assert response.status_code == 200
    assert response.json() == {"message": "processed"}


def test_hybrid_chat_completions_error_handling(setup_app):
    """Test that hybrid_chat_completions handles errors properly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make the request processor raise an exception
    setup_app["mock_request_processor"].process_request.side_effect = ValueError(
        "Test error"
    )

    # Make a request to the hybrid endpoint - this should raise an exception
    with pytest.raises(ValueError, match="Test error"):
        client.post(
            "/v2/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test message"}],
            },
        )


def test_hybrid_anthropic_messages(setup_app):
    """Test that hybrid_anthropic_messages uses the request processor correctly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the hybrid endpoint
    response = client.post(
        "/v2/anthropic/messages",
        json={
            "model": "claude-3-sonnet",
            "messages": [{"role": "user", "content": "Test message"}],
            "max_tokens": 100,
        },
    )

    # Verify that the request was processed by the mock
    setup_app["mock_request_processor"].process_request.assert_called_once()

    # Check response
    assert response.status_code == 200
    assert response.json() == {"message": "processed"}


def test_hybrid_anthropic_messages_error_handling(setup_app):
    """Test that hybrid_anthropic_messages handles errors properly."""
    # Make the request processor raise an exception
    setup_app["mock_request_processor"].process_request.side_effect = ValueError(
        "Test error"
    )

    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the hybrid endpoint - this should raise an exception
    with pytest.raises(ValueError, match="Test error"):
        client.post(
            "/v2/anthropic/messages",
            json={
                "model": "claude-3-sonnet",
                "messages": [{"role": "user", "content": "Test message"}],
                "max_tokens": 100,
            },
        )
