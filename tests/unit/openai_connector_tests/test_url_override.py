from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.openai import OpenAIConnector
from src.core.domain.chat import ChatMessage, ChatRequest

# Removed legacy import


@pytest.fixture
def mock_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def openai_connector(mock_client):
    connector = OpenAIConnector(client=mock_client)
    connector.api_key = "test-api-key"
    connector.available_models = ["gpt-3.5-turbo", "gpt-4"]
    return connector


async def test_chat_completions_uses_default_url(openai_connector, mock_client):
    """Test that chat_completions uses the default API URL when no custom URL is provided."""
    # Setup
    request_data = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )
    processed_messages = [ChatMessage(role="user", content="Hello")]
    effective_model = "gpt-3.5-turbo"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "test-id",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello there!"},
                "finish_reason": "stop",
            }
        ],
    }
    mock_response.headers = {"X-Request-ID": "test-request-id"}
    mock_client.post.return_value = mock_response

    # Execute
    await openai_connector.chat_completions(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model=effective_model,
    )

    # Verify
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert url == "https://api.openai.com/v1/chat/completions"


async def test_chat_completions_uses_custom_url(openai_connector, mock_client):
    """Test that chat_completions uses a custom URL when provided."""
    # Setup
    request_data = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )
    processed_messages = [ChatMessage(role="user", content="Hello")]
    effective_model = "gpt-3.5-turbo"
    custom_url = "https://custom-api.example.com/v1"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "test-id",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello there!"},
                "finish_reason": "stop",
            }
        ],
    }
    mock_response.headers = {"X-Request-ID": "test-request-id"}
    mock_client.post.return_value = mock_response

    # Execute
    await openai_connector.chat_completions(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model=effective_model,
        openai_url=custom_url,
    )

    # Verify
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert url == "https://custom-api.example.com/v1/chat/completions"


async def test_initialize_with_custom_url(mock_client):
    """Test that initialize uses a custom URL when provided."""
    # Setup
    connector = OpenAIConnector(client=mock_client)
    custom_url = "https://custom-api.example.com/v1"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "gpt-3.5-turbo"},
            {"id": "gpt-4"},
        ]
    }
    mock_client.get.return_value = mock_response

    # Execute
    await connector.initialize(api_key="test-api-key", api_base_url=custom_url)

    # Verify
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    url = call_args[0][0]
    assert url == "https://custom-api.example.com/v1/models"
    assert connector.api_base_url == custom_url
    assert connector.available_models == ["gpt-3.5-turbo", "gpt-4"]
