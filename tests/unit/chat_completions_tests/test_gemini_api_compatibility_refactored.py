"""
Tests for the Gemini API compatibility endpoints, using proper DI approach.

This file has been refactored to use proper dependency injection
instead of direct app.state access.
"""

from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from fastapi.testclient import TestClient
from src.core.interfaces.backend_service_interface import IBackendService

from tests.utils.test_di_utils import (
    configure_test_state,
    get_required_service_from_app,
)


@pytest.fixture
def gemini_client(client: TestClient) -> TestClient:
    """Fixture for a client with Gemini API compatibility configured."""
    # Configure the test client with proper DI instead of direct app.state access
    configure_test_state(
        client.app,
        backend_type="openrouter",  # Default backend type
        disable_interactive_commands=True,  # Disable for clean testing
        command_prefix="!/",
        api_key_redaction_enabled=False,
        backends={
            "openrouter": Mock(),
            "gemini": Mock(),
            "gemini_cli_direct": Mock(),
        },
        available_models={
            "openrouter": ["gpt-4", "gpt-3.5-turbo"],
            "gemini": ["gemini-pro", "gemini-pro-vision"],
            "gemini_cli_direct": ["gemini-2.0-flash-001"],
        },
        functional_backends=["openrouter", "gemini", "gemini_cli_direct"],
    )

    return client


class TestGeminiModelEndpoints:
    """Test the Gemini model endpoints."""

    def test_list_models(self, gemini_client):
        """Test listing models in Gemini format."""
        # Configure backend service to return our expected models
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Add list_models method if not available
        if not hasattr(backend_service, "list_models"):
            backend_service.list_models = Mock()

        backend_service.list_models.return_value = ["gemini-pro", "gemini-pro-vision"]

        response = gemini_client.get("/v1beta/models")
        assert response.status_code == 200

        # Check response format
        data = response.json()
        assert "models" in data


class TestGeminiGenerateContent:
    """Test the Gemini content generation endpoint."""

    def test_generate_content_basic(self, gemini_client):
        """Test basic content generation with Gemini format."""
        # Configure backend service to handle our call
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Set up mock async methods
        async def mock_call_completion(*args, **kwargs):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "This is a test response from Gemini"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ]
            }

        # Apply the mock async method
        backend_service.call_completion = Mock(side_effect=mock_call_completion)

        # Make request in Gemini format with proper contents to avoid validation error
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Write a short poem about programming"}],
                    "role": "user",
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.8,
                "maxOutputTokens": 100,
            },
        }

        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json=request_data
        )

        # Verify response
        assert response.status_code == 200


class TestErrorHandling:
    """Test error handling for Gemini API."""

    def test_invalid_request(self, gemini_client):
        """Test handling of invalid request."""
        # Test handling of invalid requests

        # For testing error paths, we'll use the real endpoint but with a request
        # that we expect to fail validation at some point

        # Empty request missing required fields - will fail validation
        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json={}
        )

        # We don't assert the specific code since it might be 400 or 422 or 500
        # depending on where validation happens, but we do check for error info
        assert response.status_code >= 400
        data = response.json()
        if "error" in data:
            # Check for standard error format
            assert isinstance(data["error"], dict)
        elif "detail" in data:
            # Check for Pydantic validation error format
            assert isinstance(data["detail"], list | str)
