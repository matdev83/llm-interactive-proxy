"""Tests for CommandCode OpenAI-compatible connector."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.commandcode_openai import (
    COMMANDCODE_OPENAI_BACKEND_TYPE,
    COMMANDCODE_OPENAI_DEFAULT_BASE_URL,
    CommandCodeOpenAIConnector,
)
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService


def _backend(client: httpx.AsyncClient | None = None) -> CommandCodeOpenAIConnector:
    return CommandCodeOpenAIConnector(
        client=client or httpx.AsyncClient(),
        config=AppConfig(),
        translation_service=TranslationService(),
    )


def _make_request(
    request_data: CanonicalChatRequest, effective_model: str
) -> ConnectorChatCompletionsRequest:
    return ConnectorChatCompletionsRequest(
        request=request_data,
        processed_messages=list(request_data.messages),
        effective_model=effective_model,
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
    )


def test_registered_in_backend_registry() -> None:
    """Connector should be registered for both commandcode-openai and commandcode_openai."""
    cls1 = backend_registry.get_backend_factory("commandcode-openai")
    cls2 = backend_registry.get_backend_factory("commandcode_openai")
    assert cls1 is CommandCodeOpenAIConnector
    assert cls2 is CommandCodeOpenAIConnector


@pytest.mark.asyncio
async def test_initialize_uses_explicit_api_key() -> None:
    """Connector should use provided api_key and default base URL."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": [{"id": "Qwen/Qwen3.7-Flash"}]}
    client.get.return_value = response

    connector = _backend(client)
    await connector.initialize(api_key="provided-test-key")

    assert connector.api_key == "provided-test-key"
    assert connector.api_base_url == COMMANDCODE_OPENAI_DEFAULT_BASE_URL
    assert connector.backend_type == COMMANDCODE_OPENAI_BACKEND_TYPE
    assert connector.available_models == ["Qwen/Qwen3.7-Flash"]

    await_args = client.get.await_args
    assert await_args.args[0] == f"{COMMANDCODE_OPENAI_DEFAULT_BASE_URL}/models"
    headers = await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer provided-test-key"


@pytest.mark.asyncio
async def test_initialize_uses_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connector should fall back to COMMANDCODE_API_KEY when no key is provided."""
    monkeypatch.setenv("COMMANDCODE_API_KEY", "env-commandcode-key")

    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": [{"id": "deepseek-ai/DeepSeek-V3"}]}
    client.get.return_value = response

    connector = _backend(client)
    await connector.initialize()

    assert connector.api_key == "env-commandcode-key"
    assert connector.available_models == ["deepseek-ai/DeepSeek-V3"]


@pytest.mark.asyncio
async def test_initialize_allows_base_url_override() -> None:
    """Connector should support custom api_base_url."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": []}
    client.get.return_value = response

    connector = _backend(client)
    await connector.initialize(
        api_key="test-key", api_base_url="https://custom.endpoint/provider/v1"
    )

    assert connector.api_base_url == "https://custom.endpoint/provider/v1"
    await_args = client.get.await_args
    assert await_args.args[0] == "https://custom.endpoint/provider/v1/models"


@pytest.mark.asyncio
async def test_prepare_payload_preserves_messages_and_model() -> None:
    """Payload preparation should format model and messages properly."""
    connector = _backend()
    connector.api_key = "test-key"

    request_data = CanonicalChatRequest(
        model="Qwen/Qwen3.7-Flash",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )
    processed_messages = [{"role": "user", "content": "Hello"}]

    payload = await connector._prepare_payload(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model="Qwen/Qwen3.7-Flash",
    )

    assert payload["model"] == "Qwen/Qwen3.7-Flash"
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]
    assert payload["stream"] is False


@pytest.mark.asyncio
async def test_non_streaming_chat_completions() -> None:
    """Non-streaming request should produce a valid ResponseEnvelope."""
    response = httpx.Response(
        status_code=200,
        headers={"content-type": "application/json"},
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "Qwen/Qwen3.7-Flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello world!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )
    client = AsyncMock(spec=httpx.AsyncClient)
    client.send = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)

    connector = _backend(client)
    connector.api_key = "test-key"

    request_data = CanonicalChatRequest(
        model="Qwen/Qwen3.7-Flash",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )
    req = _make_request(request_data, "Qwen/Qwen3.7-Flash")

    result = await connector._chat_completions_canonical(req)
    assert isinstance(result, ResponseEnvelope)
    assert isinstance(result.content, dict)
    assert result.content["choices"][0]["message"]["content"] == "Hello world!"


@pytest.mark.asyncio
async def test_live_commandcode_openai_end_to_end() -> None:
    """Live verification against CommandCode API when COMMANDCODE_API_KEY is present."""
    api_key = os.getenv("COMMANDCODE_API_KEY")
    if not api_key:
        pytest.skip("COMMANDCODE_API_KEY not set in environment")

    async with httpx.AsyncClient(timeout=30.0) as client:
        connector = CommandCodeOpenAIConnector(
            client=client,
            config=AppConfig(),
            translation_service=TranslationService(),
        )
        await connector.initialize(api_key=api_key)

        assert len(connector.available_models) > 0
        assert "Qwen/Qwen3.7-Flash" in connector.available_models

        # Test non-streaming live request
        request_data = CanonicalChatRequest(
            model="Qwen/Qwen3.7-Flash",
            messages=[ChatMessage(role="user", content="Say 'PONG' only")],
            stream=False,
            max_tokens=10,
        )
        req = _make_request(request_data, "Qwen/Qwen3.7-Flash")
        result = await connector._chat_completions_canonical(req)
        assert isinstance(result, ResponseEnvelope)
        assert isinstance(result.content, dict)
        text = result.content["choices"][0]["message"]["content"]
        assert "PONG" in str(text).upper()
