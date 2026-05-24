import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig


@pytest.mark.asyncio
async def test_initialize_does_not_log_raw_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    client.get.return_value = response

    config = AppConfig()
    connector = OpenAIConnector(client=client, config=config)

    caplog.set_level(logging.INFO, logger="src.connectors.openai")
    api_key = "fake_api_key_for_testing_only_12345"

    await connector.initialize(api_key=api_key)

    messages = [record.getMessage() for record in caplog.records]
    assert any("api_key_provided=yes" in message for message in messages)
    assert all(api_key not in message for message in messages)
    client.get.assert_awaited()
