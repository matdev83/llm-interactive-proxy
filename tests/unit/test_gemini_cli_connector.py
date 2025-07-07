import pytest
import httpx
import json
import secrets
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.gemini_cli import GeminiCliBackend
from src.models import ChatCompletionRequest, ChatMessage, MessageContentPartText, MessageRole
from src.security import APIKeyRedactor

MOCK_MCP_SERVER_URL = "http://localhost:12345/mcp"

@pytest.fixture
def mock_httpx_client():
    return AsyncMock(spec=httpx.AsyncClient)

@pytest.fixture
def gemini_cli_backend(mock_httpx_client):
    return GeminiCliBackend(client=mock_httpx_client, mcp_server_url=MOCK_MCP_SERVER_URL)

@pytest.fixture
def sample_chat_request():
    return ChatCompletionRequest(
        model="gemini-cli:gemini-pro", # or just "gemini-pro" if prefix is handled by proxy
        messages=[
            ChatMessage(role=MessageRole.USER, content="Hello, MCP!")
        ]
    )

@pytest.mark.asyncio
async def test_initialize_backend_with_url(mock_httpx_client):
    backend = GeminiCliBackend(client=mock_httpx_client, mcp_server_url=MOCK_MCP_SERVER_URL)
    # For now, initialize is simple and mainly logs or sets basic models.
    # If it made a test call, we'd mock that here.
    await backend.initialize()
    assert backend.mcp_server_url == MOCK_MCP_SERVER_URL
    assert "gemini-pro" in backend.get_available_models()

@pytest.mark.asyncio
async def test_initialize_backend_without_url(mock_httpx_client):
    backend = GeminiCliBackend(client=mock_httpx_client, mcp_server_url=None)
    await backend.initialize()
    # Should not raise error, but log a warning. Models might be empty or default.
    assert backend.get_available_models() == ["gemini-mcp-default"]


@pytest.mark.asyncio
async def test_chat_completions_success_non_streaming(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    request_id = secrets.token_hex(8)
    mock_mcp_response_data = {
        "jsonrpc": "2.0",
        "result": {
            "content": [{"type": "text", "text": "MCP says hello back!"}]
        },
        "id": request_id
    }
    mock_httpx_client.post.return_value = AsyncMock(
        spec=httpx.Response,
        status_code=200,
        json=lambda: mock_mcp_response_data
    )

    sample_chat_request.stream = False
    response = await gemini_cli_backend.chat_completions(
        request_data=sample_chat_request,
        processed_messages=sample_chat_request.messages,
        effective_model="gemini-pro", # Passed to ask-gemini tool
    )

    assert isinstance(response, dict)
    assert response["object"] == "chat.completion"
    assert response["choices"][0]["message"]["content"] == "MCP says hello back!"
    assert response["choices"][0]["finish_reason"] == "stop"
    assert response["model"] == "gemini-pro"

    mock_httpx_client.post.assert_called_once()
    call_args = mock_httpx_client.post.call_args
    assert call_args[0][0] == MOCK_MCP_SERVER_URL
    sent_payload = call_args[1]['json']
    assert sent_payload["method"] == "tool/call"
    assert sent_payload["params"]["name"] == "ask-gemini"
    assert sent_payload["params"]["arguments"]["prompt"] == "Hello, MCP!"
    assert sent_payload["params"]["arguments"]["model"] == "gemini-pro"

@pytest.mark.asyncio
async def test_chat_completions_success_streaming(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    request_id = secrets.token_hex(8)
    mock_mcp_response_data = {
        "jsonrpc": "2.0",
        "result": {
            "content": [{"type": "text", "text": "MCP says hello streaming!"}]
        },
        "id": request_id
    }
    mock_httpx_client.post.return_value = AsyncMock(
        spec=httpx.Response,
        status_code=200,
        json=lambda: mock_mcp_response_data
    )

    sample_chat_request.stream = True
    response = await gemini_cli_backend.chat_completions(
        request_data=sample_chat_request,
        processed_messages=sample_chat_request.messages,
        effective_model="gemini-pro",
    )

    assert isinstance(response, StreamingResponse)

    content = b""
    async for chunk in response.body_iterator:
        content += chunk

    content_str = content.decode()
    assert "data: " in content_str
    assert "MCP says hello streaming!" in content_str
    assert "data: [DONE]" in content_str

    # Check that the underlying MCP call was made once
    mock_httpx_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_chat_completions_mcp_tool_error(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    request_id = secrets.token_hex(8)
    mock_mcp_error_response = {
        "jsonrpc": "2.0",
        "error": {"code": -32000, "message": "Tool execution failed"},
        "id": request_id
    }
    mock_httpx_client.post.return_value = AsyncMock(
        spec=httpx.Response,
        status_code=200, # The HTTP call itself is fine, but MCP returns an error
        json=lambda: mock_mcp_error_response
    )

    with pytest.raises(HTTPException) as exc_info:
        await gemini_cli_backend.chat_completions(
            request_data=sample_chat_request,
            processed_messages=sample_chat_request.messages,
            effective_model="gemini-pro",
        )
    assert exc_info.value.status_code == 500
    assert "Gemini CLI tool error: Tool execution failed" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_chat_completions_http_error(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    mock_httpx_client.post.return_value = AsyncMock(
        spec=httpx.Response,
        status_code=503,
        text="Service Unavailable",
        json=lambda: {"error": "details"} # Mock for raise_for_status if it tries to parse
    )
    # Make the mock raise HTTPStatusError when raise_for_status() is called
    mock_httpx_client.post.return_value.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Service Unavailable", request=MagicMock(), response=mock_httpx_client.post.return_value))


    with pytest.raises(HTTPException) as exc_info:
        await gemini_cli_backend.chat_completions(
            request_data=sample_chat_request,
            processed_messages=sample_chat_request.messages,
            effective_model="gemini-pro",
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_chat_completions_request_error(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    mock_httpx_client.post.side_effect = httpx.RequestError("Connection failed", request=MagicMock())

    with pytest.raises(HTTPException) as exc_info:
        await gemini_cli_backend.chat_completions(
            request_data=sample_chat_request,
            processed_messages=sample_chat_request.messages,
            effective_model="gemini-pro",
        )
    assert exc_info.value.status_code == 503
    assert "Could not connect to Gemini CLI MCP server" in str(exc_info.value.detail)

@pytest.mark.asyncio
async def test_chat_completions_no_mcp_url(mock_httpx_client, sample_chat_request):
    backend = GeminiCliBackend(client=mock_httpx_client, mcp_server_url=None)
    await backend.initialize() # To set models if logic depends on it

    with pytest.raises(HTTPException) as exc_info:
        await backend.chat_completions(
            request_data=sample_chat_request,
            processed_messages=sample_chat_request.messages,
            effective_model="gemini-pro",
        )
    assert exc_info.value.status_code == 500
    assert "Gemini CLI MCP server URL is not configured" in str(exc_info.value.detail)

@pytest.mark.asyncio
async def test_chat_completions_empty_prompt(gemini_cli_backend, sample_chat_request):
    sample_chat_request.messages = [ChatMessage(role=MessageRole.USER, content="")] # Empty content

    with pytest.raises(HTTPException) as exc_info:
        await gemini_cli_backend.chat_completions(
            request_data=sample_chat_request,
            processed_messages=sample_chat_request.messages,
            effective_model="gemini-pro",
        )
    assert exc_info.value.status_code == 400
    assert "No prompt content found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_chat_completions_prompt_redaction(gemini_cli_backend, mock_httpx_client, sample_chat_request):
    api_key_to_redact = "secret_key_123"
    prompt_redactor = APIKeyRedactor([api_key_to_redact])

    sample_chat_request.messages = [
        ChatMessage(role=MessageRole.USER, content=f"My key is {api_key_to_redact} and I need help.")
    ]

    mock_mcp_response_data = {
        "jsonrpc": "2.0",
        "result": {"content": [{"type": "text", "text": "Redacted prompt processed."}]},
        "id": secrets.token_hex(8)
    }
    mock_httpx_client.post.return_value = AsyncMock(
        spec=httpx.Response, status_code=200, json=lambda: mock_mcp_response_data
    )

    await gemini_cli_backend.chat_completions(
        request_data=sample_chat_request,
        processed_messages=sample_chat_request.messages,
        effective_model="gemini-pro",
        prompt_redactor=prompt_redactor,
    )

    mock_httpx_client.post.assert_called_once()
    sent_payload = mock_httpx_client.post.call_args[1]['json']
    expected_redacted_prompt = f"My key is [REDACTED_API_KEY] and I need help."
    assert sent_payload["params"]["arguments"]["prompt"] == expected_redacted_prompt

def test_get_available_models(gemini_cli_backend):
    # Initialize is called in fixture if it sets models
    # For now, it's hardcoded in initialize or __init__
    models = gemini_cli_backend.get_available_models()
    if gemini_cli_backend.mcp_server_url: # Depends on if initialize was called with URL
        assert "gemini-pro" in models # From initialize with URL
    else: # No URL, initialize might set it to default
        assert models == ["gemini-mcp-default"]

# More tests could be added:
# - Test with different roles in messages (if logic changes to include them)
# - Test with multi-part messages if that becomes supported for prompt construction
# - Test the case where MCP response `result.content` is empty or malformed.
# - Test specific model passing to `ask-gemini` if `effective_model` is empty or different.

```
