import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from src.connectors.openai import OpenAIConnector
from src.connectors.openai_oauth import OpenAIOAuthConnector
from src.core.config.app_config import AppConfig


def test_openai_oauth_degrades_on_http_auth_error(monkeypatch):
    client = AsyncMock()
    config = AppConfig()
    connector = OpenAIOAuthConnector(client=client, config=config)
    connector.is_functional = True
    connector.api_key = "token"
    connector._auth_credentials = {"tokens": {"access_token": "token"}}

    def fake_validate_runtime_credentials(self: OpenAIOAuthConnector):
        return True, []

    async def fake_load_auth(self: OpenAIOAuthConnector) -> bool:
        return True

    async def fake_super_chat_completions(
        self: OpenAIConnector,
        request_data,
        processed_messages,
        effective_model,
        identity=None,
        **kwargs,
    ):
        raise HTTPException(status_code=401, detail="invalid token")

    monkeypatch.setattr(
        OpenAIOAuthConnector,
        "_validate_runtime_credentials",
        fake_validate_runtime_credentials,
    )
    monkeypatch.setattr(OpenAIOAuthConnector, "_load_auth", fake_load_auth)
    monkeypatch.setattr(
        OpenAIConnector, "chat_completions", fake_super_chat_completions
    )

    async def invoke_chat_completion() -> None:
        with pytest.raises(HTTPException):
            await connector.chat_completions({}, [], "gpt-test")

    asyncio.run(invoke_chat_completion())

    assert connector.is_functional is False
