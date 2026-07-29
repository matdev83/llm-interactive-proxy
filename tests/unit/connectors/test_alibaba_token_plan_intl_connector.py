"""Tests for the Alibaba international Token Plan connector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.alibaba_token_plan_intl import (
    ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL,
    AlibabaTokenPlanIntlBackend,
)
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService


def _backend() -> AlibabaTokenPlanIntlBackend:
    return AlibabaTokenPlanIntlBackend(
        client=httpx.AsyncClient(),
        config=MagicMock(spec=AppConfig),
        translation_service=TranslationService(),
    )


@pytest.mark.asyncio
async def test_initialize_uses_anthropic_defaults_and_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")
    backend = _backend()
    backend.list_models = AsyncMock()

    await backend.initialize()

    assert backend.backend_type == "alibaba-token-plan-intl"
    assert backend.key_name == "alibaba-token-plan-intl"
    assert backend.api_key == "env-secret"
    assert backend.auth_header_name == "x-api-key"
    assert backend.anthropic_api_base_url == ALIBABA_TOKEN_PLAN_INTL_DEFAULT_BASE_URL
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_initialize_allows_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")
    backend = _backend()
    backend.list_models = AsyncMock()

    await backend.initialize(anthropic_api_base_url="https://proxy.example/anthropic/")

    assert backend.anthropic_api_base_url == "https://proxy.example/anthropic"
    await backend.client.aclose()


@pytest.mark.asyncio
async def test_initialize_never_accepts_api_key_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALIBABA_TOKEN_PLAN_API_KEY", raising=False)
    backend = _backend()

    with pytest.raises(ConfigurationError, match="ALIBABA_TOKEN_PLAN_API_KEY"):
        await backend.initialize(api_key="config-secret")

    await backend.client.aclose()


@pytest.mark.asyncio
async def test_model_discovery_uses_token_plan_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALIBABA_TOKEN_PLAN_API_KEY", "env-secret")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/models"
        )
        assert request.headers["x-api-key"] == "env-secret"
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "qwen3.7-plus"}, {"id": "glm-5.2"}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    backend = AlibabaTokenPlanIntlBackend(
        client=client,
        config=MagicMock(spec=AppConfig),
        translation_service=TranslationService(),
    )
    await backend.initialize()

    assert await backend.get_available_models_async() == [
        "alibaba-token-plan-intl/qwen3.7-plus",
        "alibaba-token-plan-intl/glm-5.2",
    ]
    await client.aclose()


def test_payload_converts_every_non_user_or_system_role_to_user() -> None:
    backend = _backend()
    request = CanonicalChatRequest(
        model="qwen3.7-plus",
        messages=[ChatMessage(role="user", content="unused")],
    )

    payload = backend._prepare_anthropic_payload(
        request,
        [
            ChatMessage(role="system", content="rules"),
            ChatMessage(role="assistant", content="previous answer"),
            ChatMessage(role="developer", content="extra rules"),
            ChatMessage(role="user", content="question"),
        ],
        "qwen3.7-plus",
        None,
    )

    assert payload["system"] == "rules"
    assert payload["messages"] == [
        {"role": "user", "content": "previous answer"},
        {"role": "user", "content": "extra rules"},
        {"role": "user", "content": "question"},
    ]


def test_backend_is_registered() -> None:
    assert (
        backend_registry.get_backend_factory("alibaba-token-plan-intl")
        is AlibabaTokenPlanIntlBackend
    )
