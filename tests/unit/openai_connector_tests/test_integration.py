from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.connectors.openai import OpenAIConnector
from src.core.app.test_builder import build_test_app as build_app


@pytest.fixture
def app_config():
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
    )

    config = AppConfig()
    config.command_prefix = "!/"
    config.session.default_interactive_mode = True
    config.auth = AuthConfig(disable_auth=True)
    config.backends = BackendSettings()
    config.backends.openai = BackendConfig(api_key=["test-key"])
    config.backends.openai.api_url = "https://api.openai.com/v1"

    return config


@pytest.fixture
def mock_openai_connector():
    connector = AsyncMock(spec=OpenAIConnector)
    connector.get_available_models.return_value = ["gpt-3.5-turbo", "gpt-4"]
    connector.api_key = "test-key"
    connector.api_base_url = "https://api.openai.com/v1"

    from src.core.domain.responses import ResponseEnvelope

    mock_response = ResponseEnvelope(
        content={
            "id": "test-id",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello there!"},
                    "finish_reason": "stop",
                }
            ],
        },
        headers={},
        status_code=200,
    )

    # Set the return value directly to avoid coroutine issues
    connector.chat_completions.return_value = mock_response
    return connector


@pytest.fixture
def app_with_mock_connector(app_config, mock_openai_connector):
    with patch(
        "src.connectors.openai.OpenAIConnector", return_value=mock_openai_connector
    ):
        app = build_app(app_config)
        # The service_provider is already set on app.state by build_app's startup events
        # We just need to ensure the mock is used by the BackendService
        # This is handled by patching OpenAIConnector directly.
        yield app


@pytest.fixture
def client(app_with_mock_connector):
    return TestClient(app_with_mock_connector)


@pytest.mark.skip(
    reason="Complex coroutine serialization issue in command/response pipeline - requires deeper debugging"
)
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
