from __future__ import annotations

import pytest
from httpx import Response
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.connectors.zai import ZAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService

from tests.mocks.mock_http_client import MockHTTPClient


@pytest.fixture
def translation_service() -> TranslationService:
    return TranslationService()


@pytest.fixture
def sampling_request() -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="dummy-model",
        top_p=0.91,
        top_k=37,
    )


@pytest.mark.asyncio
async def test_qwen_prepare_payload_includes_sampling(
    translation_service: TranslationService,
    sampling_request: ChatRequest,
) -> None:
    connector = QwenOAuthConnector(
        MockHTTPClient(Response(200, json={})),
        AppConfig(),
        translation_service,
    )

    payload = await connector._prepare_payload(  # type: ignore[attr-defined]
        sampling_request,
        sampling_request.messages,
        "qwen3-coder-plus",
    )

    assert pytest.approx(payload["top_p"], rel=1e-9) == 0.91
    assert payload["top_k"] == 37


@pytest.mark.asyncio
async def test_zai_prepare_payload_includes_sampling(
    translation_service: TranslationService,
    sampling_request: ChatRequest,
) -> None:
    connector = ZAIConnector(
        MockHTTPClient(Response(200, json={})),
        AppConfig(),
        translation_service,
    )

    payload = await connector._prepare_payload(
        sampling_request,
        sampling_request.messages,
        "glm-4.5",
    )

    assert pytest.approx(payload["top_p"], rel=1e-9) == 0.91
    assert payload["top_k"] == 37
