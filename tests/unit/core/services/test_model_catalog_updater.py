import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from src.core.config.models.misc import ModelRegistryConfig
from src.core.services.model_catalog_service import ModelCatalogService
from src.core.services.model_catalog_updater import ModelCatalogUpdater


@pytest.mark.asyncio
async def test_model_catalog_updater_closes_client_on_stop() -> None:
    """The internal HTTP client is closed when the updater stops."""
    config = ModelRegistryConfig(
        download_enabled=True,
        url="http://test.com",
        bootstrap_path="test",
        cache_path="test",
    )

    catalog_service = AsyncMock(spec=ModelCatalogService)
    mock_client = AsyncMock()

    updater = ModelCatalogUpdater(config, catalog_service, http_client=mock_client)

    with patch.object(updater, "update_now", new_callable=AsyncMock):
        await updater.start()
        await updater.stop()

    mock_client.aclose.assert_called_once()


def _bootstrap_only_catalog(
    tmp_path: Path,
) -> tuple[ModelRegistryConfig, ModelCatalogService]:
    boot = {
        "bootstrap-provider": {
            "models": {"bootstrap-model": {"limit": {"context": 10, "output": 1}}}
        }
    }
    boot_path = tmp_path / "bootstrap.json"
    boot_path.write_text(json.dumps(boot), encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    config = ModelRegistryConfig(
        url="https://example.com/api.json",
        bootstrap_path=str(boot_path),
        cache_path=str(cache_path),
        download_enabled=True,
    )
    return config, ModelCatalogService(config)


@pytest.mark.asyncio
async def test_update_now_success_downloads_writes_cache_and_reloads_catalog(
    tmp_path: Path,
) -> None:
    config, catalog = _bootstrap_only_catalog(tmp_path)
    assert catalog.get_limits("bootstrap-model", None) is not None

    remote = {
        "remote-provider": {
            "models": {
                "remote-model": {"limit": {"context": 5000, "output": 500}},
            }
        }
    }

    client = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.get(config.url).mock(
                return_value=httpx.Response(200, json=remote),
            )
            updater = ModelCatalogUpdater(config, catalog, http_client=client)
            assert await updater.update_now() is True

        cache_file = Path(config.cache_path)
        assert cache_file.is_file()
        assert "remote-provider" in cache_file.read_text(encoding="utf-8")

        assert catalog.get_limits("remote-model", None) is not None
        assert catalog.get_limits("remote-model", None).context_window == 5000
        assert catalog.get_limits("bootstrap-model", None) is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_update_now_http_error_returns_false(tmp_path: Path) -> None:
    config, catalog = _bootstrap_only_catalog(tmp_path)
    client = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.get(config.url).mock(return_value=httpx.Response(503))
            updater = ModelCatalogUpdater(config, catalog, http_client=client)
            assert await updater.update_now() is False
        assert catalog.get_limits("bootstrap-model", None) is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_update_now_empty_dict_response_returns_false(tmp_path: Path) -> None:
    config, catalog = _bootstrap_only_catalog(tmp_path)
    client = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.get(config.url).mock(return_value=httpx.Response(200, json={}))
            updater = ModelCatalogUpdater(config, catalog, http_client=client)
            assert await updater.update_now() is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_update_now_non_dict_json_returns_false(tmp_path: Path) -> None:
    config, catalog = _bootstrap_only_catalog(tmp_path)
    client = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.get(config.url).mock(return_value=httpx.Response(200, json=[1, 2, 3]))
            updater = ModelCatalogUpdater(config, catalog, http_client=client)
            assert await updater.update_now() is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_update_now_blocked_url_returns_false(tmp_path: Path) -> None:
    boot_path = tmp_path / "bootstrap.json"
    boot_path.write_text(
        json.dumps(
            {
                "p": {
                    "models": {
                        "m": {"limit": {"context": 1, "output": 1}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = ModelRegistryConfig(
        url="http://127.0.0.1/api.json",
        bootstrap_path=str(boot_path),
        cache_path=str(tmp_path / "cache.json"),
        download_enabled=True,
    )
    catalog = ModelCatalogService(config)
    client = httpx.AsyncClient()
    try:
        updater = ModelCatalogUpdater(config, catalog, http_client=client)
        assert await updater.update_now() is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_start_skips_background_loop_when_download_disabled(
    tmp_path: Path,
) -> None:
    boot_path = tmp_path / "bootstrap.json"
    boot_path.write_text(
        json.dumps({"p": {"models": {"m": {"limit": {"context": 1, "output": 1}}}}}),
        encoding="utf-8",
    )
    config = ModelRegistryConfig(
        url="https://example.com/api.json",
        bootstrap_path=str(boot_path),
        cache_path=str(tmp_path / "cache.json"),
        download_enabled=False,
    )
    catalog = ModelCatalogService(config)
    updater = ModelCatalogUpdater(config, catalog, http_client=AsyncMock())
    await updater.start()
    assert updater._task is None
    await updater.stop()
