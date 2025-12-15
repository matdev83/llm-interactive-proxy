from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.zenmux import ZenmuxConnector
from src.core.config.app_config import AppConfig

ZENMUX_BASE_URL = "https://zenmux.ai/api/v1"


@pytest.mark.asyncio
async def test_initialize_uses_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zenmux connector should read ZENMUX_API_KEY when no key is provided."""
    monkeypatch.setenv("ZENMUX_API_KEY", "env-zenmux-key")

    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": [{"id": "zenmux/model-a"}]}
    response.status_code = 200
    client.get.return_value = response

    connector = ZenmuxConnector(client, config=AppConfig())
    await connector.initialize()

    assert connector.api_key == "env-zenmux-key"
    assert connector.available_models == ["zenmux/model-a"]
    await_args = client.get.await_args
    assert await_args.args[0] == f"{ZENMUX_BASE_URL}/models"
    headers = await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer env-zenmux-key"
    assert (
        headers["HTTP-Referer"] == "https://github.com/matdev83/llm-interactive-proxy"
    )
    assert headers["X-Title"] == "llm-interactive-proxy"
    assert (
        "x-llmproxy-loop-guard" in headers
    )  # Base connector always injects guard header


@pytest.mark.asyncio
async def test_list_models_respects_override() -> None:
    """list_models should allow overriding the base URL when needed."""
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {"data": []}
    response.status_code = 200
    client.get.return_value = response

    connector = ZenmuxConnector(client, config=AppConfig())
    connector.api_key = "provided-key"

    await connector.list_models(api_base_url="https://alt.api")

    await_args = client.get.await_args
    assert await_args.args[0] == "https://alt.api/models"
    headers = await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer provided-key"
