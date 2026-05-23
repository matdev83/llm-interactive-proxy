"""In-process NvidiaConnector: list_models + canonical chat with mocked NVIDIA upstream."""

from __future__ import annotations

import pytest

pytest.importorskip("respx")

import httpx
from respx import MockRouter
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.nvidia import NvidiaConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

_BASE = "https://integrate.api.nvidia.com/v1"
_MODEL = "stepfun-ai/step-3.5-flash"


def _models_payload() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": _MODEL,
                "object": "model",
                "created": 1,
                "owned_by": "meta",
            },
        ],
    }


def _chat_payload() -> dict:
    return {
        "id": "chatcmpl-nvidia-ip",
        "object": "chat.completion",
        "created": 1700000000,
        "model": _MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "mocked assistant reply",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }


@pytest.mark.asyncio
async def test_nvidia_connector_list_models_and_chat_in_process(
    respx_mock: MockRouter,
) -> None:
    respx_mock.get(f"{_BASE}/models").mock(
        return_value=httpx.Response(200, json=_models_payload())
    )
    respx_mock.post(f"{_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_chat_payload())
    )

    async with httpx.AsyncClient(timeout=30.0) as http:
        connector = NvidiaConnector(
            http, AppConfig(), translation_service=TranslationService()
        )
        await connector.initialize(api_key="integration-in-process-nvidia")

        listing = await connector.list_models()
        ids = [m.id for m in listing.data]
        assert _MODEL in ids
        assert connector.get_available_models()

        domain = CanonicalChatRequest(
            model=_MODEL,
            messages=[ChatMessage(role="user", content="ping")],
            stream=False,
            max_completion_tokens=16,
        )
        req = ConnectorChatCompletionsRequest(
            request=domain,
            processed_messages=list(domain.messages),
            effective_model=_MODEL,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )
        env = await connector.chat_completions(req)

    assert isinstance(env, ResponseEnvelope)
    body = env.content
    assert isinstance(body, dict)
    assert body["choices"][0]["message"]["content"] == "mocked assistant reply"
