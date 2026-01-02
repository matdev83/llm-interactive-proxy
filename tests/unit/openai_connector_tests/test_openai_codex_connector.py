import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from src.connectors.openai import OpenAIConnector
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


def test_openai_codex_degrades_on_http_auth_error(monkeypatch):
    client = AsyncMock()
    config = AppConfig()
    mock_translation_service = AsyncMock(spec=TranslationService)
    connector = OpenAICodexConnector(
        client=client, config=config, translation_service=mock_translation_service
    )
    connector.is_functional = True
    connector.api_key = "token"
    connector._auth_credentials = {"tokens": {"access_token": "token"}}

    async def fake_validate_runtime_credentials(self: OpenAICodexConnector):
        return True

    async def fake_load_auth(self: OpenAICodexConnector) -> bool:
        return True

    mock_chat_completions = AsyncMock(
        side_effect=HTTPException(status_code=401, detail="invalid token")
    )

    monkeypatch.setattr(
        OpenAICodexConnector,
        "_validate_runtime_credentials",
        fake_validate_runtime_credentials,
    )
    monkeypatch.setattr(OpenAICodexConnector, "_load_auth", fake_load_auth)
    monkeypatch.setattr(OpenAIConnector, "chat_completions", mock_chat_completions)

    async def invoke_chat_completion() -> None:
        with pytest.raises(HTTPException):
            request = CanonicalChatRequest(
                model="gpt-test",
                messages=[ChatMessage(role="user", content="test")],
            )
            await connector.chat_completions(request, [], "gpt-test")

    asyncio.run(invoke_chat_completion())

    assert connector.is_functional is False
