"""Test model list resolution for the Ollama connector.

Verifies that ``OllamaConnector.initialize`` returns a combined list of
local models (from the local Ollama server, always fetched live) and
cloud models (fetched from ``ollama.com/api/tags`` with ``-cloud``
suffix and cached with a TTL).
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import src.connectors.ollama as ollama_module
from src.connectors.ollama import (
    OllamaConnector,
    _clear_cloud_models_cache,
    _fetch_cloud_models,
)
from src.core.config.app_config import AppConfig


def _make_mock_client(local_response_json: dict) -> AsyncMock:
    """Return a mock local httpx.AsyncClient that serves local model data."""
    local_response = MagicMock()
    local_response.status_code = 200
    local_response.json.return_value = local_response_json
    client = AsyncMock()
    client.get.return_value = local_response
    return client


@pytest.fixture(autouse=True)
def _reset_cloud_cache() -> Generator[None, None, None]:
    """Ensure every test starts with a clean cloud-model cache."""
    _clear_cloud_models_cache()
    yield
    _clear_cloud_models_cache()


# ------------------------------------------------------------------
# Model list merging: local + cloud
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_list_merges_local_and_cloud_with_cloud_suffix() -> None:
    """Connector returns local models plus cloud models suffixed with ``-cloud``."""
    local_models_data = [{"id": "llama3:8b"}, {"id": "mistral:7b"}]
    client = _make_mock_client({"data": local_models_data})
    connector = OllamaConnector(client, config=AppConfig())

    cloud_models = ["deepseek-v3.2-cloud", "gemma3:27b-cloud"]
    with patch.object(
        ollama_module, "_fetch_cloud_models", AsyncMock(return_value=cloud_models)
    ):
        await connector.initialize()

    assert connector.available_models == [
        "llama3:8b",
        "mistral:7b",
        "deepseek-v3.2-cloud",
        "gemma3:27b-cloud",
    ]


@pytest.mark.asyncio
async def test_model_list_returns_only_local_when_cloud_fetch_fails() -> None:
    """If cloud model fetch fails (returns empty), connector still returns local models."""
    local_models_data = [{"id": "codellama:7b"}]
    client = _make_mock_client({"data": local_models_data})
    connector = OllamaConnector(client, config=AppConfig())

    with patch.object(ollama_module, "_fetch_cloud_models", AsyncMock(return_value=[])):
        await connector.initialize()

    assert connector.available_models == ["codellama:7b"]


@pytest.mark.asyncio
async def test_model_list_returns_empty_when_local_unavailable_but_cloud_works() -> (
    None
):
    """If local models endpoint fails but cloud works, return only cloud models."""
    client = AsyncMock()
    client.get.side_effect = ConnectionError("refused")
    connector = OllamaConnector(client, config=AppConfig())

    with patch.object(
        ollama_module,
        "_fetch_cloud_models",
        AsyncMock(return_value=["llama3:latest-cloud"]),
    ):
        await connector.initialize()

    assert connector.available_models == ["llama3:latest-cloud"]


@pytest.mark.asyncio
async def test_model_list_empty_local_and_cloud() -> None:
    """Returns empty list when both endpoints return no models."""
    local_models_data: list[dict] = []
    client = _make_mock_client({"data": local_models_data})
    connector = OllamaConnector(client, config=AppConfig())

    with patch.object(ollama_module, "_fetch_cloud_models", AsyncMock(return_value=[])):
        await connector.initialize()

    assert connector.available_models == []


# ------------------------------------------------------------------
# Cloud suffix verification
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_models_get_cloud_suffix() -> None:
    """Cloud models from the /api/tags endpoint get the ``-cloud`` suffix appended."""
    local_models_data: list[dict] = []
    client = _make_mock_client({"data": local_models_data})
    connector = OllamaConnector(client, config=AppConfig())

    expected_cloud = [
        "qwen3-coder:480b-cloud",
        "kimi-k2-thinking-cloud",
        "gemma4:31b-cloud",
    ]
    with patch.object(
        ollama_module, "_fetch_cloud_models", AsyncMock(return_value=expected_cloud)
    ):
        await connector.initialize()

    for model in connector.available_models:
        assert model.endswith("-cloud")
    assert connector.available_models == expected_cloud


# ------------------------------------------------------------------
# Cloud models fetch: suffix and graceful error handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_cloud_models_appends_cloud_suffix() -> None:
    """``_fetch_cloud_models`` appends ``-cloud`` to every model name from the API."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.raise_for_status = MagicMock()
    api_response.json.return_value = {
        "models": [
            {"name": "llama3:latest"},
            {"name": "mistral:7b-instruct"},
            {"name": "qwen3:32b"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=api_response)
    mock_client.is_closed = False

    with patch.object(ollama_module, "_cloud_models_client", mock_client):
        models = await _fetch_cloud_models(force=True)

    assert models == [
        "llama3:latest-cloud",
        "mistral:7b-instruct-cloud",
        "qwen3:32b-cloud",
    ]


@pytest.mark.asyncio
async def test_fetch_cloud_models_handles_api_error_gracefully() -> None:
    """``_fetch_cloud_models`` returns empty list when the API call fails."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("network unreachable")
    mock_client.is_closed = False

    with patch.object(ollama_module, "_cloud_models_client", mock_client):
        models = await _fetch_cloud_models(force=True)

    assert models == []


# ------------------------------------------------------------------
# Cloud models TTL cache
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_models_cache_returns_stored_value_on_second_call() -> None:
    """Second call within TTL returns cached result without re-fetching."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.raise_for_status = MagicMock()
    api_response.json.return_value = {"models": [{"name": "llama3:latest"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=api_response)
    mock_client.is_closed = False

    with patch.object(ollama_module, "_cloud_models_client", mock_client):
        first = await _fetch_cloud_models(force=False)
        second = await _fetch_cloud_models(force=False)

    assert first == second == ["llama3:latest-cloud"]
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_cloud_models_cache_refreshes_after_ttl_expires() -> None:
    """After TTL expires, the next call re-fetches from the upstream."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.raise_for_status = MagicMock()
    api_response.json.return_value = {"models": [{"name": "llama3:latest"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=api_response)
    mock_client.is_closed = False

    with (
        patch.object(ollama_module, "_cloud_models_client", mock_client),
        patch.object(ollama_module, "time") as mock_time,
    ):
        mock_time.monotonic.return_value = 0.0
        first = await _fetch_cloud_models(force=False)
        assert len(first) == 1

        mock_time.monotonic.return_value = ollama_module._CLOUD_MODEL_TTL + 100
        second = await _fetch_cloud_models(force=False)

    assert len(second) == 1
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_clear_cloud_models_cache_forces_refetch() -> None:
    """Clearing the cache forces the next fetch call to hit the API."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.raise_for_status = MagicMock()
    api_response.json.return_value = {"models": [{"name": "codellama:7b"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=api_response)
    mock_client.is_closed = False

    with patch.object(ollama_module, "_cloud_models_client", mock_client):
        first = await _fetch_cloud_models(force=False)
        _clear_cloud_models_cache()
        second = await _fetch_cloud_models(force=False)

    assert first == second == ["codellama:7b-cloud"]
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_force_bypasses_cache() -> None:
    """force=True always refetches regardless of cached value."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.raise_for_status = MagicMock()
    api_response.json.return_value = {"models": [{"name": "mistral:7b"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=api_response)
    mock_client.is_closed = False

    with patch.object(ollama_module, "_cloud_models_client", mock_client):
        await _fetch_cloud_models(force=False)
        await _fetch_cloud_models(force=False)
        assert mock_client.get.call_count == 1

        await _fetch_cloud_models(force=True)

    assert mock_client.get.call_count == 2
