"""Tests for the direct controllers without hybrid controller."""

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
async def setup_app(app):
    """Set up the app with necessary services for testing."""
    # Create mock services
    from fastapi import Response

    # Create a mock response with proper body and status code
    mock_response = Response(
        content=b'{"message": "processed"}',
        status_code=200,
        media_type="application/json",
    )

    mock_request_processor = AsyncMock()
    mock_request_processor.process_request = AsyncMock(return_value=mock_response)

    # Set up service provider
    mock_provider = MagicMock()
    mock_provider.get_service.return_value = mock_request_processor
    mock_provider.get_required_service.return_value = mock_request_processor

    # Add service provider to app state
    app.state.service_provider = mock_provider

    # Add routes
    from fastapi import Body, Depends, Request
    from src.anthropic_models import AnthropicMessagesRequest
    from src.core.app.controllers import (
        get_anthropic_controller_if_available,
        get_chat_controller_if_available,
    )
    from src.core.domain.chat import ChatRequest

    @app.post("/v2/chat/completions")
    async def chat_completions(
        request: Request,
        request_data: ChatRequest = Body(...),
        controller=Depends(get_chat_controller_if_available),
    ):
        return await controller.handle_chat_completion(request, request_data)

    @app.post("/v2/anthropic/messages")
    async def anthropic_messages(
        request: Request,
        request_data: AnthropicMessagesRequest = Body(...),
        controller=Depends(get_anthropic_controller_if_available),
    ):
        return await controller.handle_anthropic_messages(request, request_data)

    yield {
        "app": app,
        "mock_provider": mock_provider,
        "mock_request_processor": mock_request_processor,
    }


def test_chat_controller(setup_app):
    """Test that chat controller uses the request processor correctly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the endpoint
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


def test_chat_controller_error_handling(setup_app):
    """Test that chat controller handles errors properly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make the request processor raise an exception
    setup_app["mock_request_processor"].process_request.side_effect = ValueError(
        "Test error"
    )

    # Make a request to the endpoint - this should return a 500 error
    response = client.post(
        "/v2/chat/completions",
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Test message"}],
        },
    )

    # Check that we got a 500 error
    assert response.status_code == 500
    assert "Test error" in response.text


def test_anthropic_controller(setup_app):
    """Test that anthropic controller uses the request processor correctly."""
    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the endpoint
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


def test_anthropic_controller_error_handling(setup_app):
    """Test that anthropic controller handles errors properly."""
    # Make the request processor raise an exception
    setup_app["mock_request_processor"].process_request.side_effect = ValueError(
        "Test error"
    )

    # Create test client
    client = TestClient(setup_app["app"])

    # Make a request to the endpoint - this should return a 500 error
    response = client.post(
        "/v2/anthropic/messages",
        json={
            "model": "claude-3-sonnet",
            "messages": [{"role": "user", "content": "Test message"}],
            "max_tokens": 100,
        },
    )

    # Check that we got a 500 error
    assert response.status_code == 500
    assert "Test error" in response.text
