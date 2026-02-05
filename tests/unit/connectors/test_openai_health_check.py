from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


@pytest.mark.asyncio
async def test_health_check_handles_read_error() -> None:
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ReadError("boom"))

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=TranslationService(),
    )
    connector.api_key = "test-key"
    connector.api_base_url = "https://api.openai.com/v1"

    assert await connector._perform_health_check() is False
    client.get.assert_awaited_once()
