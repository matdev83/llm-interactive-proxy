"""Integration tests for Anthropic backend functionality."""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.domain.responses import ResponseEnvelope

# Mock Anthropic response for testing
MOCK_ANTHROPIC_RESPONSE = {
    "id": "msg_013Zva2CMHLNnXjNJJKqJ2EF",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": "Hello! This is a mock response from the Anthropic backend.",
        }
    ],
    "model": "test-model",
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 20},
}


@pytest.fixture
def app():
    """Create a test app with Anthropic backend configuration."""
    from src.core.config.app_config import AuthConfig, BackendSettings

    # Configure for Anthropic backend
    anthropic_backend = BackendConfig(api_key=["test-key"])
    backends = BackendSettings(default_backend="anthropic", anthropic=anthropic_backend)
    auth_config = AuthConfig(disable_auth=True)

    config = AppConfig(backends=backends, auth=auth_config)
    app = build_app(config=config)
    return app


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return TestClient(app)


@pytest.mark.integration
@pytest.mark.no_global_mock
def test_end_to_end_chat_completion(client):
    """Test end-to-end chat completion with Anthropic backend."""

    # Mock the backend service call_completion to return our test response
    # We patch call_completion instead of create_backend because backends might be cached
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
        mock_call_completion.return_value = ResponseEnvelope(
            content=MOCK_ANTHROPIC_RESPONSE,
            headers={"content-type": "application/json"},
            status_code=200,
        )

        # Create request data
        request_data = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "Hello!"}],
        }

        # Make request through the proxy
        response = client.post("/anthropic/v1/messages", json=request_data)

        # Validate response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        result = response.json()

        # Check that we get the expected structure
        assert "content" in result
        assert len(result["content"]) > 0
        # Check that we have valid content (could be text or tool_use)
        content_item = result["content"][0]
        assert "type" in content_item
        # Either text content or tool use content should be present
        assert (
            "text" in content_item and content_item["text"] is not None
        ) or "name" in content_item
        assert "usage" in result


# Test matrix scenarios (reduced for performance)
SCENARIOS = [
    ("anthropic", "claude-3-haiku-20240307"),
]


@pytest.mark.integration
@pytest.mark.no_global_mock
@pytest.mark.parametrize("client_type,model", SCENARIOS)
def test_scenarios_chat_completion(client, client_type, model):
    """Test different scenarios with chat completion."""

    # Mock the backend service call_completion to return our test response
    # We patch call_completion instead of create_backend because backends might be cached
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
        mock_call_completion.return_value = ResponseEnvelope(
            content=MOCK_ANTHROPIC_RESPONSE,
            headers={"content-type": "application/json"},
            status_code=200,
        )

        # Create request data
        request_data = {
            "model": model,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "Hello!"}],
        }

        # Make request through the proxy
        response = client.post("/anthropic/v1/messages", json=request_data)

        # Validate response
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        result = response.json()

        # Check that we get the expected structure
        assert "content" in result
        assert len(result["content"]) > 0
        # Check that we have valid content (could be text or tool_use)
        content_item = result["content"][0]
        assert "type" in content_item
        # Either text content or tool use content should be present
        assert (
            "text" in content_item and content_item["text"] is not None
        ) or "name" in content_item
        assert "usage" in result
