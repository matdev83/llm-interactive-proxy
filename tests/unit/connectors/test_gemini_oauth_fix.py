import json
from unittest.mock import AsyncMock, MagicMock, patch

import google.auth.exceptions
import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.response_processor_interface import ProcessedResponse

pytestmark = pytest.mark.skip(
    reason="Connector-level streaming error shaping changed; behavior validated in resilience layer."
)


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

    connector = AntigravityOAuthConnector(client, config, translation_service)
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

    connector = AntigravityOAuthConnector(client, config, translation_service)
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


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_stream_generator_yields_usage_merged_with_stop():
    """Test that usage is merged into the final stop chunk."""
    # Mock dependencies
    client = AsyncMock()
    config = MagicMock()
    translation_service = MagicMock()

    # Setup translation service to pass through chunks
    def mock_to_domain(chunk, source_format):
        if chunk is None:
            return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        return chunk

    translation_service.to_domain_stream_chunk.side_effect = mock_to_domain

    connector = AntigravityOAuthConnector(client, config, translation_service)
    connector.gemini_api_base_url = "https://example.com"
    connector._oauth_credentials = {"access_token": "fake_token"}

    # Mock response with a single chunk that has both content and stop reason
    chunk_data = {
        "choices": [{"delta": {"content": "Hello world"}, "finish_reason": "stop"}]
    }

    # Create a mock response that yields this chunk and then ends
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_content = MagicMock(
        return_value=[f"data: {json.dumps(chunk_data)}\n\n".encode()]
    )
    mock_response.headers = {"Content-Type": "text/event-stream"}

    # Mock AuthorizedSession
    with patch("google.auth.transport.requests.AuthorizedSession") as mock_auth_cls:
        mock_session = MagicMock()
        mock_session.request.return_value = mock_response
        mock_auth_cls.return_value = mock_session

        # Run the generator
        chunks = []
        envelope = await connector._chat_completions_code_assist_streaming(
            request_data=MagicMock(),
            processed_messages=[{"role": "user", "content": "test"}],
            effective_model="gemini-2.5-pro",
        )
        async for chunk in envelope.content:
            chunks.append(chunk)

    # Verify we got chunks
    # With merge logic, we should get 1 chunk that has content+stop+usage
    assert len(chunks) == 1

    chunk = chunks[0]
    assert isinstance(chunk.content, dict)

    # Check usage presence
    assert "usage" in chunk.content
    # prompt_tokens is calculated as 0 because we mock the input
    # completion_tokens is calculated via tiktoken from "Hello world" (2 tokens)
    assert chunk.content["usage"]["prompt_tokens"] >= 0
    assert chunk.content["usage"]["completion_tokens"] == 2
    assert chunk.content["usage"]["total_tokens"] >= 2

    # Check stop reason
    choices = chunk.content.get("choices", [])
    assert choices and choices[0].get("finish_reason") == "stop"
