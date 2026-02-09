from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.kimi_code import KimiCodeConnector
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _build_connector() -> KimiCodeConnector:
    connector = KimiCodeConnector(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    connector.api_key = "test-key"
    return connector


@pytest.mark.asyncio
async def test_prepare_payload_allows_large_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector()
    monkeypatch.setenv("KIMI_CONTINUATION_MAX_BYTES", "300")
    monkeypatch.setenv("KIMI_CONTINUATION_WARN_BYTES", "100")

    oversized_payload = {
        "model": "kimi/kimi-for-coding",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "x" * 600},
        ],
    }

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hello")],
    )

    with patch(
        "src.connectors.openai.OpenAIConnector._prepare_payload",
        new=AsyncMock(return_value=oversized_payload),
    ):
        payload = await connector._prepare_payload(
            request, request.messages, request.model
        )

    assert payload["messages"][1]["content"] == "x" * 600


@pytest.mark.asyncio
async def test_prepare_payload_allows_large_first_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _build_connector()
    monkeypatch.setenv("KIMI_CONTINUATION_MAX_BYTES", "200")

    first_turn_payload = {
        "model": "kimi/kimi-for-coding",
        "messages": [
            {"role": "user", "content": "x" * 600},
        ],
    }

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hello")],
    )

    with patch(
        "src.connectors.openai.OpenAIConnector._prepare_payload",
        new=AsyncMock(return_value=first_turn_payload),
    ):
        payload = await connector._prepare_payload(
            request, request.messages, request.model
        )

    assert payload["messages"][0]["content"] == "x" * 600


@pytest.mark.asyncio
async def test_prepare_payload_logs_warning_when_threshold_is_configured(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = _build_connector()
    monkeypatch.setenv("KIMI_CONTINUATION_WARN_BYTES", "100")

    continuation_payload = {
        "model": "kimi/kimi-for-coding",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "x" * 600},
        ],
    }

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hello")],
    )

    with (
        caplog.at_level(logging.WARNING),
        patch(
            "src.connectors.openai.OpenAIConnector._prepare_payload",
            new=AsyncMock(return_value=continuation_payload),
        ),
    ):
        await connector._prepare_payload(request, request.messages, request.model)

    assert "Kimi continuation payload size=" in caplog.text
