from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


def _build_response(content: str) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        request=httpx.Request("GET", "https://api.openai.com/v1/models"),
        content=content.encode("utf-8"),
    )


@pytest.mark.asyncio
async def test_initialize_strips_xssi_guard(mock_client: AsyncMock) -> None:
    mock_translation_service = MagicMock(spec=TranslationService)
    connector = OpenAIConnector(
        client=mock_client,
        config=AppConfig(),
        translation_service=mock_translation_service,
    )
    payload = ')]}\',\n{"data":[{"id":"gpt-4"}]}'
    mock_client.get = AsyncMock(return_value=_build_response(payload))

    await connector.initialize(api_key="sk-test")

    assert connector.available_models == ["gpt-4"]
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialize_handles_trailing_payload(mock_client: AsyncMock) -> None:
    mock_translation_service = MagicMock(spec=TranslationService)
    connector = OpenAIConnector(
        client=mock_client,
        config=AppConfig(),
        translation_service=mock_translation_service,
    )
    payload = '{"data":[{"id":"gpt-4o"}]}\n<!-- html comment -->'
    mock_client.get = AsyncMock(return_value=_build_response(payload))

    await connector.initialize(api_key="sk-test")

    assert connector.available_models == ["gpt-4o"]
