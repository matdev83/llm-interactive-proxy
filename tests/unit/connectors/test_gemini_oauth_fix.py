from unittest.mock import AsyncMock, MagicMock, patch

import google.auth.exceptions
import pytest
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.mark.asyncio
async def test_stream_generator_yields_dict_on_error():
    """Verify that stream_generator yields a dict (not SSE string) on error."""
    # Mock dependencies
    client = AsyncMock()
    config = MagicMock()
    # Mock translation service to return a dict
    translation_service = MagicMock()
    translation_service.to_domain_stream_chunk.return_value = {
        "choices": [{"delta": {}, "finish_reason": "error"}],
        "error": {"message": "Not found", "code": 404},
    }

    connector = GeminiOAuthAntigravityConnector(client, config, translation_service)
    connector.gemini_api_base_url = "https://example.com"
    connector._oauth_credentials = {"access_token": "fake"}

    # Mock auth session using patch.object
    auth_session = MagicMock()
    # Mock the request method specifically to avoid any real calls
    auth_session.request = MagicMock()

    # Mock response
    response = MagicMock()
    response.status_code = 404
    response.json.return_value = {"error": {"message": "Not found", "code": 404}}

    # Mock AuthorizedSession
    with patch("google.auth.transport.requests.AuthorizedSession") as mock_auth_cls:
        mock_session = MagicMock()
        mock_session.request.return_value = response
        mock_auth_cls.return_value = mock_session

        # Call the method
        request_data = CanonicalChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )
        processed_messages = request_data.messages
        effective_model = "test-model"

        envelope = await connector._chat_completions_code_assist_streaming(
            request_data, processed_messages, effective_model
        )

        # Iterate over the stream
        chunks = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        # Verify
        assert len(chunks) == 1
        chunk = chunks[0]
        assert isinstance(chunk, ProcessedResponse)
        content = chunk.content

        # It should be a dict, NOT a string starting with "data: "
        assert isinstance(content, dict)
        assert content["error"]["code"] == 404
        assert content["error"]["message"] == "Not found"
        assert content["choices"][0]["finish_reason"] == "error"


@pytest.mark.asyncio
async def test_stream_generator_handles_google_auth_error():
    """Verify that stream_generator catches GoogleAuthError and yields an error dict."""
    # Mock dependencies
    client = AsyncMock()
    config = MagicMock()
    translation_service = MagicMock()
    # Mock translation service to return a dict
    translation_service.to_domain_stream_chunk.return_value = {
        "choices": [{"delta": {}, "finish_reason": "error"}],
        "error": {"message": "Auth failed", "code": 401},
    }

    connector = GeminiOAuthAntigravityConnector(client, config, translation_service)
    connector.gemini_api_base_url = "https://example.com"
    connector._oauth_credentials = {"access_token": "fake"}

    # Mock AuthorizedSession
    with patch("google.auth.transport.requests.AuthorizedSession") as mock_auth_cls:
        mock_session = MagicMock()
        mock_session.request.side_effect = google.auth.exceptions.GoogleAuthError(
            "Refresh failed"
        )
        mock_auth_cls.return_value = mock_session

        # Call the method
        request_data = CanonicalChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )
        processed_messages = request_data.messages
        effective_model = "test-model"

        envelope = await connector._chat_completions_code_assist_streaming(
            request_data, processed_messages, effective_model
        )

        # Iterate over the stream
        chunks = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        # Verify
        assert len(chunks) == 1
        chunk = chunks[0]
        assert isinstance(chunk, ProcessedResponse)
        content = chunk.content

        # It should be a dict describing the auth error
        assert isinstance(content, dict)
        assert content["error"]["code"] == 401
        assert content["error"]["type"] == "auth_error"
        assert "Authentication failed" in content["error"]["message"]
