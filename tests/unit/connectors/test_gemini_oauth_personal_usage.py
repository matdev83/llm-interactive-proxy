from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


@pytest.mark.asyncio
async def test_chat_completions_with_tiktoken_usage_calculation():
    """
    Test that token usage is calculated using tiktoken when the backend
    response does not include it.
    """
    # Arrange
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    connector = GeminiOAuthPersonalConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )

    # Set the API base URL, which is normally done in the initialize method
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"

    # Mock dependencies
    connector._oauth_credentials = {"access_token": "fake_token"}
    connector._discover_project_id = AsyncMock(return_value="fake_project")
    mock_translation_service.to_domain_request.return_value = ChatRequest(
        model="gemini-pro", messages=[ChatMessage(role="user", content="Hello")]
    )
    mock_translation_service.from_domain_to_gemini_request.return_value = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}]
    }

    # Mock the response from the Code Assist API (without usage data)
    mock_sse_response = MagicMock()
    mock_sse_response.text = 'data: {"choices": [{"delta": {"content": "World"}}], "finish_reason": "stop"}\n\ndata: [DONE]\n'
    mock_sse_response.status_code = 200

    # Mock the auth_session and its request method
    mock_auth_session = MagicMock()
    mock_auth_session.request.return_value = mock_sse_response

    # Mock the translation service for the response
    mock_translation_service.to_domain_stream_chunk.return_value = {
        "choices": [{"delta": {"content": "World"}}]
    }
    mock_translation_service.from_domain_to_openai_response.side_effect = (
        lambda response: {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response.choices[0].message.content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": response.usage,
        }
    )

    request_data = ChatRequest(
        model="gemini-cli-oauth-personal:gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Act
    with patch(
        "google.auth.transport.requests.AuthorizedSession",
        return_value=mock_auth_session,
    ):
        result = await connector._chat_completions_code_assist(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gemini-pro",
        )

    # Assert
    assert isinstance(result, ResponseEnvelope)
    assert result.usage is not None
    assert result.usage["prompt_tokens"] > 0
    assert result.usage["completion_tokens"] > 0
    assert (
        result.usage["total_tokens"]
        == result.usage["prompt_tokens"] + result.usage["completion_tokens"]
    )

    # Specific token counts for 'Hello' and 'World' with cl100k_base
    # 'Hello' -> 1 token
    # 'World' -> 1 token
    assert result.usage["prompt_tokens"] == 1
    assert result.usage["completion_tokens"] == 1
    assert result.usage["total_tokens"] == 2


@pytest.mark.asyncio
async def test_chat_completions_streaming_with_tiktoken_usage_calculation():
    """
    Test that token usage is calculated and yielded as a final chunk in streaming.
    """
    # Arrange
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    connector = GeminiOAuthPersonalConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector._oauth_credentials = {"access_token": "fake_token"}
    connector._discover_project_id = AsyncMock(return_value="fake_project")

    mock_translation_service.to_domain_request.return_value = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hello stream")],
        stream=True,
    )
    mock_translation_service.from_domain_to_gemini_request.return_value = {
        "contents": [{"role": "user", "parts": [{"text": "Hello stream"}]}]
    }

    # Mock the response from the Code Assist API
    mock_response = MagicMock()
    mock_response.status_code = 200

    def mock_iter_content(*args, **kwargs):
        # Simulate character-by-character streaming as the real API does
        data = b'data: {"choices": [{"delta": {"content": "Streamed "}}]}\ndata: {"choices": [{"delta": {"content": "World"}}]}\ndata: [DONE]\n'
        for byte in data:
            yield bytes([byte])

    mock_response.iter_content = mock_iter_content

    mock_auth_session = MagicMock()
    mock_auth_session.request.return_value = mock_response

    # Mock translation for stream chunks
    def stream_chunk_translator(chunk, source_format):
        if chunk is None:
            return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        return chunk

    mock_translation_service.to_domain_stream_chunk.side_effect = (
        stream_chunk_translator
    )

    request_data = ChatRequest(
        model="gemini-cli-oauth-personal:gemini-pro",
        messages=[ChatMessage(role="user", content="Hello stream")],
        stream=True,
    )

    # Act
    with patch(
        "google.auth.transport.requests.AuthorizedSession",
        return_value=mock_auth_session,
    ):
        result_envelope = await connector._chat_completions_code_assist_streaming(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello stream")],
            effective_model="gemini-pro",
        )

    # Assert
    assert isinstance(result_envelope, StreamingResponseEnvelope)

    all_chunks = []
    async for chunk in result_envelope.content:
        all_chunks.append(chunk.content)

    assert len(all_chunks) == 4  # 2 content chunks, 1 usage chunk, 1 done chunk

    # Check content chunks
    assert all_chunks[0]["choices"][0]["delta"]["content"] == "Streamed "
    assert all_chunks[1]["choices"][0]["delta"]["content"] == "World"

    # Check usage chunk
    usage_chunk = all_chunks[2]
    assert "usage" in usage_chunk
    assert usage_chunk["usage"]["prompt_tokens"] == 2  # "Hello stream"
    assert (
        usage_chunk["usage"]["completion_tokens"] == 3
    )  # "Streamed " + "World" = 3 tokens
    assert usage_chunk["usage"]["total_tokens"] == 5  # 2 prompt + 3 completion

    # Check final chunk
    assert all_chunks[3]["choices"][0]["finish_reason"] == "stop"
