"""Tests that Nvidia connector preserves usage for OpenAI-compatible responses (Req 4.3)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.nvidia import NvidiaConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.response_adapters import to_fastapi_response


@pytest.mark.asyncio
async def test_nvidia_non_streaming_response_includes_usage() -> None:
    """Non-streaming completion JSON with usage populates ResponseEnvelope.usage."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.nvidia = None

    translation_service = TranslationService()

    connector = NvidiaConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test-nvidia-key"
    connector.api_base_url = "https://integrate.api.nvidia.com/v1"
    connector.disable_health_check()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-type": "application/json",
        "x-request-id": "nvidia-req-1",
    }
    mock_response.json.return_value = {
        "id": "chatcmpl-nvidia-1",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "meta/llama3-70b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    mock_response.aread = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="meta/llama3-70b",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=False,
    )
    domain = CanonicalChatRequest.model_validate(request.model_dump())
    connector_req = ConnectorChatCompletionsRequest(
        request=domain,
        processed_messages=list(request.messages),
        effective_model="meta/llama3-70b",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    result = await connector.chat_completions(connector_req)

    assert isinstance(result, ResponseEnvelope)
    assert result.usage is not None
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["completion_tokens"] == 5
    assert result.usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_nvidia_usage_in_client_response_via_fastapi_adapter() -> None:
    """Usage from Nvidia-shaped JSON flows through to FastAPI response body."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock(spec=AppConfig)
    mock_config.backends = MagicMock()
    mock_config.backends.nvidia = None

    translation_service = TranslationService()

    connector = NvidiaConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )

    connector.api_key = "test_key"
    connector.api_base_url = "https://integrate.api.nvidia.com/v1"
    connector.disable_health_check()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "id": "chatcmpl-nvidia-2",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "meta/llama3-8b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Out"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 30,
            "completion_tokens": 20,
            "total_tokens": 50,
        },
    }
    mock_response.aread = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)

    request = ChatRequest(
        model="meta/llama3-8b",
        messages=[ChatMessage(role="user", content="In")],
        stream=False,
    )
    domain = CanonicalChatRequest.model_validate(request.model_dump())
    connector_req = ConnectorChatCompletionsRequest(
        request=domain,
        processed_messages=list(request.messages),
        effective_model="meta/llama3-8b",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )

    envelope = await connector.chat_completions(connector_req)

    fastapi_response = to_fastapi_response(envelope)
    response_body = json.loads(fastapi_response.body)

    assert "usage" in response_body
    assert response_body["usage"]["prompt_tokens"] == 30


def test_sse_final_chunk_with_usage_parsed_like_openai_stream() -> None:
    """OpenAI-style SSE final chunk with usage uses the same translation path as Nvidia streaming."""
    translation_service = TranslationService()

    payload = {
        "id": "chatcmpl-stream-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "meta/llama3-70b",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }

    sse_message = f"data: {json.dumps(payload)}\n\n"

    domain_chunk = translation_service.to_domain_stream_chunk(sse_message, "openai")

    dumped = (
        domain_chunk.model_dump(exclude_none=True)
        if hasattr(domain_chunk, "model_dump")
        else domain_chunk
    )
    assert isinstance(dumped, dict)
    usage = dumped.get("usage")
    assert usage is not None
    # Usage may be dict or UsageSummary-shaped
    prompt = (
        usage.get("prompt_tokens") if isinstance(usage, dict) else usage.prompt_tokens
    )
    completion = (
        usage.get("completion_tokens")
        if isinstance(usage, dict)
        else usage.completion_tokens
    )
    total = usage.get("total_tokens") if isinstance(usage, dict) else usage.total_tokens
    assert prompt == 12
    assert completion == 8
    assert total == 20
