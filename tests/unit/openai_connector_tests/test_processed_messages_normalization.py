from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
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

    await connector.chat_completions(
        request,
        processed_messages,
        "gpt-4",
        identity=None,
    )

    assert observed_payloads, "Expected payload normalization to occur"
    payload = observed_payloads[0]
    # The payload should contain normalized content
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
