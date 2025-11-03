import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)

from src.connectors.openai import OpenAIConnector
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseHandle
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_client():
    return AsyncMock(spec=AsyncClient)


@pytest.fixture
def mock_config():
    return MagicMock(spec=AppConfig)


@pytest.fixture
def mock_translation_service():
    return MagicMock(spec=TranslationService)


@pytest.fixture
async def backend(mock_client, mock_config, mock_translation_service):
    with patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}):
        model_response = MagicMock()
        model_response.json.return_value = {
            "data": [
                {
                    "id": "glm-4.6",
                    "name": "glm-4.6",
                },
                {
                    "id": "claude-sonnet-4-20250514",
                    "name": "claude-sonnet-4-20250514",
                },
            ]
        }
        model_response.raise_for_status = MagicMock()
        mock_client.get.return_value = model_response
        backend = ZaiCodingPlanBackend(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )
        await backend.initialize(api_key="test-key")
        return backend


async def test_backend_initialization(backend: ZaiCodingPlanBackend):
    assert backend.backend_type == "zai-coding-plan"
    # ZAI now uses OpenAI-compatible API
    assert backend.api_base_url == "https://api.z.ai/api/coding/paas/v4"
    assert backend.anthropic_api_base_url == backend.api_base_url  # For backward compat
    assert backend.api_key == "test-key"


async def test_get_available_models(backend: ZaiCodingPlanBackend):
    models = await backend.get_available_models_async()
    assert models[0] == "glm-4.6"
    assert "claude-sonnet-4-20250514" in models


async def test_list_models(backend: ZaiCodingPlanBackend):
    models = await backend.list_models()
    assert "data" in models
    returned_ids = {m["id"] for m in models["data"]}
    assert "glm-4.6" in returned_ids
    assert "claude-sonnet-4-20250514" in returned_ids


async def test_chat_completions_preserves_model(
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "test",
        "model": "claude-sonnet-4-20250514",
    }
    mock_response.headers = {"content-type": "application/json"}
    mock_response.status_code = 200

    backend.client.post = AsyncMock(return_value=mock_response)

    mock_translation_service.from_domain_request.return_value = {
        "model": "glm-4.6",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }

    processed_messages = [ChatMessage(role="user", content="hello")]
    result = await backend.chat_completions(
        ChatRequest(
            model="zai-coding-plan:glm-4.6",
            messages=processed_messages,
        ),
        processed_messages,
        "glm-4.6",
    )

    # Verify the client was called with the correct payload
    backend.client.post.assert_called_once()
    call_args = backend.client.post.call_args
    payload = call_args[1]["json"]
    assert payload["model"] == "glm-4.6"

    # Verify the response is returned (model rewriting is handled by parent OpenAI connector)
    assert result is not None


async def test_get_headers_includes_kilo_metadata(backend: ZaiCodingPlanBackend):
    headers = backend.get_headers()
    assert headers["User-Agent"].startswith("Kilo-Code/")
    assert headers["HTTP-Referer"] == "https://kilocode.ai"
    assert headers["Referer"] == "https://kilocode.ai"
    assert headers["Origin"] == "https://kilocode.ai"
    assert headers["X-Title"] == "Kilo Code"
    assert "Authorization" in headers


@pytest.mark.asyncio
async def test_chat_completions_retries_with_legacy_on_1113(
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    error = HTTPException(
        status_code=429,
        detail={
            "message": "Insufficient balance or no resource package. Please recharge."
        },
    )
    success = ResponseEnvelope(content={"id": "ok"}, headers={}, status_code=200)

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        AsyncMock(side_effect=[error, success]),
    ) as mock_super:
        processed_messages = [ChatMessage(role="user", content="hello")]
        request = ChatRequest(
            model="zai-coding-plan:glm-4.6",
            messages=processed_messages,
            stream=False,
        )

        result = await backend.chat_completions(
            request,
            processed_messages,
            "glm-4.6",
        )

    assert result == success
    assert mock_super.call_count == 2
    first_call_args = mock_super.call_args_list[0][0]
    second_call_args = mock_super.call_args_list[1][0]
    assert first_call_args[2] == "glm-4.6"
    assert second_call_args[2] == backend._LEGACY_MODEL


@pytest.mark.asyncio
async def test_chat_completions_raises_rate_limit_error(
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    error = HTTPException(
        status_code=429,
        detail={"message": "Insufficient balance"},
    )

    backend.available_models = ["glm-4.6"]
    backend._provider_models = {"glm-4.6"}

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        AsyncMock(side_effect=[error]),
    ):
        processed_messages = [ChatMessage(role="user", content="hello")]
        request = ChatRequest(
            model="glm-4.6",
            messages=processed_messages,
            stream=False,
        )

        with pytest.raises(RateLimitExceededError) as exc_info:
            await backend.chat_completions(request, processed_messages, "glm-4.6")

    assert "Insufficient balance" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_completions_unknown_model_raises_backend_error(
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    error = HTTPException(
        status_code=400,
        detail={"message": "Unknown Model"},
    )

    backend.available_models = ["glm-4.6"]
    backend._provider_models = {"glm-4.6"}

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        AsyncMock(side_effect=[error]),
    ):
        processed_messages = [ChatMessage(role="user", content="hello")]
        request = ChatRequest(
            model="glm-4.6",
            messages=processed_messages,
            stream=False,
        )

        with pytest.raises(BackendError) as exc_info:
            await backend.chat_completions(request, processed_messages, "glm-4.6")

    assert exc_info.value.status_code == 400
    assert "Unknown Model" in str(exc_info.value)


@pytest.mark.asyncio
async def test_streaming_attempt_completion_emits_sanitized_chunk(
    backend: ZaiCodingPlanBackend,
):
    async def original_stream():
        payloads = [
            {
                "id": "chunk-1",
                "model": "glm-4.6",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "<attempt_completion>\n<result>Success",
                        },
                    }
                ],
            },
            {
                "id": "chunk-1",
                "model": "glm-4.6",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": " case resolved</result></attempt_completion>",
                        },
                    }
                ],
            },
            {
                "id": "chunk-1",
                "model": "glm-4.6",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": ""},
                        "finish_reason": "stop",
                    }
                ],
            },
        ]

        for payload in payloads:
            yield ProcessedResponse(content=f"data: {json.dumps(payload)}\n\n")

    mock_handle = StreamingResponseHandle(
        iterator=original_stream(), cancel_callback=AsyncMock(), headers={}
    )

    with patch.object(
        OpenAIConnector,
        "_handle_streaming_response",
        AsyncMock(return_value=mock_handle),
    ):
        wrapped_handle = await backend._handle_streaming_response(
            url="https://api.z.ai/api/coding/paas/v4/chat/completions",
            payload={"model": "glm-4.6"},
            headers={},
            session_id="session-1",
            stream_format="sse",
        )

    collected = []
    async for chunk in wrapped_handle.iterator:
        if isinstance(chunk.content, str) and chunk.content.startswith("data: "):
            data = json.loads(chunk.content[len("data: ") :])
            delta = data.get("choices", [{}])[0].get("delta", {})
            if data.get("id", "").startswith("hybrid-sanitized-"):
                collected.append(delta.get("content"))

    assert collected == ["Success case resolved"]
