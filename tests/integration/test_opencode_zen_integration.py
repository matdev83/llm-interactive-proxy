"""
Integration tests for OpenCode Zen connector.

These tests simulate the full flow of the connector including initialization,
credential management, and chat completion requests, using mocked HTTP responses
but real file system interactions (via tmp_path).
"""

import json
import os
import time

import pytest
import respx
from httpx import Response
from src.connectors.opencode_zen import OpencodeZenConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_credentials_file(tmp_path):
    """Create a temporary credentials file."""
    creds_dir = tmp_path / "opencode"
    creds_dir.mkdir(parents=True)
    creds_file = creds_dir / "auth.json"

    creds_data = {
        "opencode": {
            "type": "oauth",
            "access": "test-access-token-1",
            "refresh": "test-refresh-token-1",
            "expires": int(time.time()) + 3600,
        }
    }
    creds_file.write_text(json.dumps(creds_data), encoding="utf-8")
    return creds_file


@pytest.fixture
async def connector(tmp_path):
    """Create a connector instance."""
    config = AppConfig()
    translation_service = TranslationService()

    # Create client with httpx for respx mocking
    import httpx

    client = httpx.AsyncClient()

    connector = OpencodeZenConnector(client, config, translation_service)
    yield connector
    await client.aclose()


@pytest.mark.asyncio
async def test_full_flow_with_credentials(connector, mock_credentials_file):
    """Test full flow: init -> chat completion."""

    # Mock API response
    with respx.mock(base_url="https://api.gateway.opencode.ai/v1") as respx_mock:
        respx_mock.get("/models").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        {"id": "openai/gpt-4.1"},
                        {"id": "anthropic/claude-sonnet-4"},
                    ]
                },
            )
        )

        respx_mock.post("/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "chatcmpl-123",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "gpt-4.1",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Hello from OpenCode Zen!",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            )
        )

        # 1. Initialize
        await connector.initialize(credentials_path=str(mock_credentials_file))
        assert connector.is_functional

        # 2. Request chat completion
        request = ChatRequest(
            model="opencode-zen:openai/gpt-4.1",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )

        response = await connector.chat_completions(
            request, request.messages, "opencode-zen:openai/gpt-4.1"
        )

        # 3. Verify response
        # OpenAIConnector returns the raw response dict in content for non-streaming
        assert (
            response.content["choices"][0]["message"]["content"]
            == "Hello from OpenCode Zen!"
        )

        # 4. Verify Auth header was sent
        last_request = respx_mock.calls.last.request
        assert last_request.headers["Authorization"] == "Bearer test-access-token-1"
        assert last_request.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_token_refresh_flow(connector, mock_credentials_file):
    """Test flow where token expires and is reloaded from file."""

    with respx.mock(base_url="https://api.gateway.opencode.ai/v1") as respx_mock:
        respx_mock.get("/models").mock(
            return_value=Response(200, json={"data": [{"id": "openai/gpt-4.1"}]})
        )

        respx_mock.post("/chat/completions").mock(
            return_value=Response(
                200,
                json={"choices": [{"message": {"content": "OK"}}]},
            )
        )

        # 1. Initialize with valid credentials
        await connector.initialize(credentials_path=str(mock_credentials_file))

        # 2. Simulate token expiry in memory
        connector._oauth_credentials["expires"] = time.time() - 100

        # 3. Update file with NEW credentials (as if CLI refreshed it)
        new_creds = {
            "opencode": {
                "type": "oauth",
                "access": "test-access-token-2",  # NEW TOKEN
                "refresh": "test-refresh-token-2",
                "expires": int(time.time()) + 3600,
            }
        }
        mock_credentials_file.write_text(json.dumps(new_creds), encoding="utf-8")
        # Update mtime to force reload
        os.utime(mock_credentials_file, None)

        # 4. Make request - should trigger reload and use NEW token
        request = ChatRequest(
            model="opencode-zen:openai/gpt-4.1",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )

        await connector.chat_completions(
            request, request.messages, "opencode-zen:openai/gpt-4.1"
        )

        # 5. Verify NEW token was used
        last_request = respx_mock.calls.last.request
        assert last_request.headers["Authorization"] == "Bearer test-access-token-2"


@pytest.mark.asyncio
async def test_streaming_response(connector, mock_credentials_file):
    """Test streaming response handling."""

    # Mock streaming response
    stream_content = [
        'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}\n\n',
        'data: {"id":"2","choices":[{"delta":{"content":" World"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def content_stream():
        for chunk in stream_content:
            yield chunk.encode()

    with respx.mock(base_url="https://api.gateway.opencode.ai/v1") as respx_mock:
        respx_mock.get("/models").mock(
            return_value=Response(200, json={"data": [{"id": "openai/gpt-4.1"}]})
        )

        respx_mock.post("/chat/completions").mock(
            return_value=Response(
                200,
                content=content_stream(),
                headers={"Content-Type": "text/event-stream"},
            )
        )

        await connector.initialize(credentials_path=str(mock_credentials_file))

        request = ChatRequest(
            model="opencode-zen:openai/gpt-4.1",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )

        response_handle = await connector.chat_completions(
            request, request.messages, "opencode-zen:openai/gpt-4.1"
        )

        # Consume stream
        chunks = []
        async for chunk in response_handle.content:
            chunks.append(chunk)

        # Verify content
        content_parts = []
        debug_chunks = []
        for chunk in chunks:
            debug_chunks.append(chunk.content)

            # Handle both parsed dicts and raw bytes (SSE)
            if isinstance(chunk.content, dict):
                choices = chunk.content.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta:
                        content_parts.append(delta["content"])
            elif isinstance(chunk.content, bytes | str):
                raw_content = chunk.content
                if isinstance(raw_content, bytes):
                    raw_content = raw_content.decode("utf-8")

                for line in raw_content.splitlines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if "content" in delta:
                                    content_parts.append(delta["content"])
                        except json.JSONDecodeError:
                            pass

        full_content = "".join(content_parts)
        if full_content != "Hello World":
            pytest.fail(
                f"Expected 'Hello World', got '{full_content}'. Chunks content: {debug_chunks}"
            )
        assert full_content == "Hello World"
