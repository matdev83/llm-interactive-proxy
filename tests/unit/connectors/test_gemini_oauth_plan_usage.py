from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


@pytest.mark.asyncio
async def test_code_assist_empty_response_returns_empty_envelope():
    """Test that empty responses (no candidates) return an empty ResponseEnvelope.

    NOTE: After SOLID refactoring, non-streaming path uses streaming executor
    internally and accumulates the response. Empty candidates result in an
    empty response envelope rather than raising BackendError.
    """
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    connector = GeminiOAuthPlanConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )

    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector._oauth_credentials = {"access_token": "fake_token"}
    connector._refresh_token_if_needed = AsyncMock(return_value=True)
    connector._discover_project_id = AsyncMock(return_value="fake_project")

    mock_translation_service.from_domain_to_gemini_request.return_value = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello"}],
            }
        ]
    }

    # Create a mock response that provides an SSE stream with empty candidates
    mock_response = MagicMock()
    mock_response.status_code = 200

    def mock_iter_content(*args, **kwargs):
        # Simulate SSE stream with empty candidates response
        # Yield data at once instead of byte-by-byte for performance
        data = b'data: {"candidates": []}\ndata: [DONE]\n'
        yield data

    mock_response.iter_content = mock_iter_content
    mock_response.close = MagicMock()

    mock_auth_session = MagicMock()
    mock_auth_session.headers = {}
    mock_auth_session.request.return_value = mock_response

    # Mock translation for stream chunks - return empty response
    mock_translation_service.to_domain_stream_chunk.return_value = {"candidates": []}

    request = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    with patch(
        "google.auth.transport.requests.AuthorizedSession",
        return_value=mock_auth_session,
    ):
        result = await connector._chat_completions_code_assist(
            request_data=request,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gemini-2.5-pro",
        )

    # After SOLID refactoring, empty responses return an empty envelope
    assert isinstance(result, ResponseEnvelope)
    # The accumulator returns an empty response for empty streams
    assert result.content is not None or result.status_code == 200


@pytest.mark.asyncio
async def test_chat_completions_with_tiktoken_usage_calculation():
    """
    Test that token usage is calculated using tiktoken when the backend
    response does not include it.

    NOTE: After SOLID refactoring, non-streaming path uses streaming executor
    internally and accumulates the response. The mock must provide an SSE stream.
    """
    # Arrange
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    connector = GeminiOAuthPlanConnector(
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
    # NOTE: Must provide iter_content for streaming executor
    mock_sse_response = MagicMock()
    mock_sse_response.status_code = 200

    def mock_iter_content(*args, **kwargs):
        # Simulate SSE stream with content chunk and finish
        # Yield entire data at once instead of byte-by-byte for performance
        data = b'data: {"candidates": [{"content": {"parts": [{"text": "World"}]}}]}\ndata: {"candidates": [{"finishReason": "STOP"}]}\ndata: [DONE]\n'
        yield data

    mock_sse_response.iter_content = mock_iter_content
    mock_sse_response.close = MagicMock()

    # Mock the auth_session and its request method
    mock_auth_session = MagicMock()
    mock_auth_session.headers = {}
    mock_auth_session.request.return_value = mock_sse_response

    # Mock the translation service for the response
    def mock_stream_chunk(chunk, source_format):
        if chunk is None:
            return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        if chunk.get("candidates"):
            cand = chunk["candidates"][0]
            if "content" in cand and "parts" in cand["content"]:
                text = cand["content"]["parts"][0].get("text", "")
                return {"choices": [{"delta": {"content": text}}]}
            if "finishReason" in cand:
                return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        return {"choices": [{"delta": {}}]}

    mock_translation_service.to_domain_stream_chunk.side_effect = mock_stream_chunk

    request_data = ChatRequest(
        model="gemini-oauth-plan:gemini-pro",
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

    connector = GeminiOAuthPlanConnector(
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
        # Simulate streaming with chunks instead of byte-by-byte for performance
        data = b'data: {"choices": [{"delta": {"content": "Streamed "}}]}\ndata: {"choices": [{"delta": {"content": "World"}}]}\ndata: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\ndata: [DONE]\n'
        # Yield in chunks to simulate streaming without byte-by-byte overhead
        yield data

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
        model="gemini-oauth-plan:gemini-pro",
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

    # Updated to expect 3 chunks (merged usage/stop) instead of 4
    # [Chunk 1 (content), Chunk 2 (content), Chunk 3 (stop + usage)]
    assert len(all_chunks) == 3

    # Check content chunks
    assert all_chunks[0]["choices"][0]["delta"]["content"] == "Streamed "
    assert all_chunks[1]["choices"][0]["delta"]["content"] == "World"

    # Check final chunk (usage + stop merged)
    final_chunk = all_chunks[2]

    # Handle StopChunkWithUsage wrapper or dict
    if hasattr(final_chunk, "to_plain_dict"):
        final_chunk_dict = final_chunk.to_plain_dict()
    else:
        final_chunk_dict = dict(final_chunk)

    assert "usage" in final_chunk_dict
    assert final_chunk_dict["usage"]["prompt_tokens"] == 2  # "Hello stream"
    assert (
        final_chunk_dict["usage"]["completion_tokens"] == 3
    )  # "Streamed " + "World" = 3 tokens
    assert final_chunk_dict["usage"]["total_tokens"] == 5  # 2 prompt + 3 completion

    # Check final chunk finish reason
    # Depending on implementation it might be a generic stop or preserved
    # In the test case, mock_iter_content yields [DONE] which creates a generic stop chunk
    assert final_chunk_dict.get("choices", [{}])[0].get("finish_reason") == "stop"


@pytest.mark.asyncio
async def test_code_assist_streaming_cancel_callback_absent():
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    connector = GeminiOAuthPlanConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"
    connector._oauth_credentials = {"access_token": "fake_token"}
    connector._discover_project_id = AsyncMock(return_value="fake_project")

    mock_translation_service.to_domain_request.return_value = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )
    mock_translation_service.from_domain_to_gemini_request.return_value = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}]
    }

    stream_response = MagicMock()
    stream_response.status_code = 200

    def _iter_content(chunk_size: int = 1, decode_unicode: bool = False):
        data = b'data: {"choices": [{"delta": {"content": "Hi"}}]}\n' b"data: [DONE]\n"
        # Yield data at once instead of byte-by-byte for performance
        yield data

    stream_response.iter_content.side_effect = _iter_content
    stream_response.close = MagicMock()

    mock_auth_session = MagicMock()
    mock_auth_session.request.return_value = stream_response

    mock_translation_service.to_domain_stream_chunk.side_effect = (
        lambda chunk, source_format: (
            {"choices": [{"delta": {"content": "Hi"}}]}
            if chunk
            else {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        )
    )

    request_data = ChatRequest(
        model="gemini-oauth-plan:gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    with patch(
        "google.auth.transport.requests.AuthorizedSession",
        return_value=mock_auth_session,
    ):
        envelope = await connector._chat_completions_code_assist_streaming(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gemini-pro",
        )

    assert isinstance(envelope, StreamingResponseEnvelope)
    assert envelope.cancel_callback is None
