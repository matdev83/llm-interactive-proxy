from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.connectors.openai import OpenAIConnector
from src.core.app.test_builder import build_test_app as build_app


@pytest.fixture
def app_config():
    return {
        "command_prefix": "!/",
        "interactive_mode": True,
        "openai_api_keys": {"OPENAI_API_KEY": "test-key"},
        "openai_api_base_url": "https://api.openai.com/v1",
        "disable_auth": True,
    }


@pytest.fixture
def mock_openai_connector():
    connector = AsyncMock(spec=OpenAIConnector)
    connector.get_available_models.return_value = ["gpt-3.5-turbo", "gpt-4"]
    connector.api_key = "test-key"
    connector.api_base_url = "https://api.openai.com/v1"

    async def mock_chat_completions(
        request_data, processed_messages, effective_model, **kwargs
    ):
        # Check if openai_url is being passed correctly
        if kwargs.get("openai_url"):
            assert kwargs["openai_url"] == "https://custom-api.example.com/v1"

        return {
            "id": "test-id",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello there!"},
                    "finish_reason": "stop",
                }
            ],
        }, {}

    connector.chat_completions.side_effect = mock_chat_completions
    return connector


@pytest.fixture
def app_with_mock_connector(app_config, mock_openai_connector):
    with patch(
        "src.connectors.openai.OpenAIConnector", return_value=mock_openai_connector
    ):
        app, _ = build_app(app_config)
        # The service_provider is already set on app.state by build_app's startup events
        # We just need to ensure the mock is used by the BackendService
        # This is handled by patching OpenAIConnector directly.
        yield app


@pytest.fixture
def client(app_with_mock_connector):
    return TestClient(app_with_mock_connector)


def test_set_openai_url_command(client):
    """Test that the !set(openai_url=...) command works correctly."""
    # Set the OpenAI URL
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(openai_url=https://custom-api.example.com/v1)",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert "OpenAI URL set to" in response.json()["choices"][0]["message"]["content"]
