from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.config.models.misc import ReasoningModelTokenFloorConfig
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    MessageContentPartText,
)
from src.core.domain.responses import ResponseEnvelope


@pytest.mark.asyncio
async def test_prepare_payload_handles_sequence_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure list-based message content does not raise during payload normalization."""

    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "gpt-4",
        "messages": [],
    }

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    connector.disable_health_check()
    connector.api_key = "test-token"

    observed_payloads: list[dict[str, Any]] = []

    async def fake_handle(
        self: OpenAIConnector,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
        context: Any = None,
    ) -> ResponseEnvelope:
        observed_payloads.append(payload)
        return ResponseEnvelope(content={}, headers={}, status_code=200)

    monkeypatch.setattr(
        OpenAIConnector,
        "_handle_non_streaming_response",
        fake_handle,
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(text="first"),
                    MessageContentPartText(text="second"),
                ],
            )
        ],
        stream=False,
    )

    processed_messages = [
        ChatMessage(
            role="user",
            content=[
                MessageContentPartText(text="first"),
                MessageContentPartText(text="second"),
            ],
        )
    ]

    connector_req = ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=processed_messages,
        effective_model="gpt-4",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )
    await connector.chat_completions(connector_req)

    assert observed_payloads, "Expected payload normalization to occur"
    payload = observed_payloads[0]
    # The payload should contain normalized content
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]


@pytest.mark.asyncio
async def test_prepare_payload_applies_stepfun_min_token_floor() -> None:
    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "stepfun/step-3.5-flash:free",
        "messages": [],
        "max_tokens": 64,
    }

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    request = CanonicalChatRequest(
        model="stepfun/step-3.5-flash:free",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
    )

    payload = await connector._prepare_payload(
        request,
        request.messages,
        "openrouter:stepfun/step-3.5-flash:free",
        context=None,
    )
    assert payload["max_tokens"] == 512


@pytest.mark.asyncio
async def test_prepare_payload_applies_kimi_min_token_floor() -> None:
    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "kimi/kimi-for-coding",
        "messages": [],
        "max_completion_tokens": 64,
    }

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hi")],
        max_completion_tokens=64,
    )

    payload = await connector._prepare_payload(
        request,
        request.messages,
        "kimi/kimi-for-coding",
        context=None,
    )
    assert payload["max_completion_tokens"] == 512


@pytest.mark.asyncio
async def test_prepare_payload_does_not_change_non_target_model_tokens() -> None:
    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "gpt-4",
        "messages": [],
        "max_tokens": 64,
    }

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
    )

    payload = await connector._prepare_payload(
        request,
        request.messages,
        "gpt-4",
        context=None,
    )
    assert payload["max_tokens"] == 64


@pytest.mark.asyncio
async def test_prepare_payload_skips_token_floor_when_disabled() -> None:
    """When reasoning_model_token_floor.enabled is False, token floor is not applied."""
    config = AppConfig()
    config = config.model_copy(
        update={
            "reasoning_model_token_floor": ReasoningModelTokenFloorConfig(
                enabled=False,
                models={"stepfun/step-3.5-flash:free": 512},
            )
        }
    )
    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "stepfun/step-3.5-flash:free",
        "messages": [],
        "max_tokens": 64,
    }

    connector = OpenAIConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )
    request = CanonicalChatRequest(
        model="stepfun/step-3.5-flash:free",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
    )

    payload = await connector._prepare_payload(
        request,
        request.messages,
        "openrouter:stepfun/step-3.5-flash:free",
        context=None,
    )
    assert payload["max_tokens"] == 64


@pytest.mark.asyncio
async def test_prepare_payload_uses_custom_model_floor_from_config() -> None:
    """Config models override default floors."""
    config = AppConfig()
    config = config.model_copy(
        update={
            "reasoning_model_token_floor": ReasoningModelTokenFloorConfig(
                enabled=True,
                models={"stepfun/step-3.5-flash:free": 256},
            )
        }
    )
    client = AsyncMock()
    translation_service = MagicMock()
    translation_service.from_domain_request.return_value = {
        "model": "stepfun/step-3.5-flash:free",
        "messages": [],
        "max_tokens": 64,
    }

    connector = OpenAIConnector(
        client=client,
        config=config,
        translation_service=translation_service,
    )
    request = CanonicalChatRequest(
        model="stepfun/step-3.5-flash:free",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
    )

    payload = await connector._prepare_payload(
        request,
        request.messages,
        "openrouter:stepfun/step-3.5-flash:free",
        context=None,
    )
    assert payload["max_tokens"] == 256
