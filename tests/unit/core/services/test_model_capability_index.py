from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import BackendConfig
from src.core.services.model_capability_index import (
    ModelCapabilityDiscoverer,
    ModelCapabilityIndex,
    ModelCapabilityRefreshController,
)


def _mock_config_provider(configs: dict[str, BackendConfig]) -> Mock:
    provider = Mock()
    provider.get_backend_config.side_effect = lambda name: configs.get(name)
    provider.iter_backend_names.side_effect = lambda: list(configs.keys())
    return provider


def test_index_from_config_provider_builds_canonical_and_alias_lookups() -> None:
    provider = _mock_config_provider(
        {
            "openai.1": BackendConfig(models=["openai/gpt-4o"]),
            "openai.2": BackendConfig(models=["gpt-4o"]),
            "anthropic.1": BackendConfig(models=["anthropic/claude-3-haiku"]),
        }
    )

    index = ModelCapabilityIndex.from_config_provider(provider)

    assert index.get_candidates("openai/gpt-4o") == ["openai.1", "openai.2"]
    assert index.get_candidates("gpt-4o") == ["openai.1", "openai.2"]
    assert index.get_candidates("anthropic/claude-3-haiku") == ["anthropic.1"]
    assert index.get_candidates("claude-3-haiku") == ["anthropic.1"]


@pytest.mark.asyncio
async def test_discoverer_prefers_live_enumeration_with_config_hint_fallback() -> None:
    provider = _mock_config_provider(
        {
            "openai.1": BackendConfig(models=["openai/gpt-4o-hint"]),
            "anthropic.1": BackendConfig(models=["anthropic/claude-3-haiku"]),
        }
    )

    openai_backend = Mock()
    openai_backend.get_available_models_async = AsyncMock(
        return_value=["openai/gpt-4o"]
    )

    lifecycle = Mock()
    lifecycle.get_active_backends.return_value = {"openai.1": openai_backend}

    discoverer = ModelCapabilityDiscoverer(
        config_provider=provider,
        backend_lifecycle_manager=lifecycle,
    )
    snapshot = await discoverer.discover_snapshot()

    assert snapshot.model_to_instances["openai/gpt-4o"] == ("openai.1",)
    assert snapshot.model_to_instances["anthropic/claude-3-haiku"] == ("anthropic.1",)


@pytest.mark.asyncio
async def test_refresh_controller_retains_last_known_good_snapshot_on_failure() -> None:
    provider = _mock_config_provider(
        {"openai.1": BackendConfig(models=["openai/gpt-4o"])}
    )
    index = ModelCapabilityIndex.from_config_provider(provider)

    good_snapshot = index.get_snapshot()

    discoverer = Mock()
    discoverer.discover_snapshot = AsyncMock(
        side_effect=[good_snapshot, RuntimeError("boom")]
    )

    controller = ModelCapabilityRefreshController(
        index=index,
        discoverer=discoverer,
        refresh_interval_seconds=0.0,
        failure_backoff_seconds=30.0,
    )

    assert await controller.refresh_now(reason="startup")
    generation_after_success = index.get_snapshot().generation

    assert not await controller.refresh_now(reason="on-demand")
    assert index.get_snapshot().generation == generation_after_success


@pytest.mark.asyncio
async def test_refresh_controller_enforces_backoff_after_failure() -> None:
    provider = _mock_config_provider(
        {"openai.1": BackendConfig(models=["openai/gpt-4o"])}
    )
    index = ModelCapabilityIndex.from_config_provider(provider)

    discoverer = Mock()
    discoverer.discover_snapshot = AsyncMock(side_effect=RuntimeError("boom"))

    controller = ModelCapabilityRefreshController(
        index=index,
        discoverer=discoverer,
        refresh_interval_seconds=0.0,
        failure_backoff_seconds=30.0,
    )

    assert not await controller.refresh_now(reason="startup")
    assert not await controller.refresh_now(reason="on-demand")
    assert discoverer.discover_snapshot.await_count == 1


@pytest.mark.asyncio
async def test_refresh_controller_serializes_concurrent_refreshes() -> None:
    provider = _mock_config_provider(
        {"openai.1": BackendConfig(models=["openai/gpt-4o"])}
    )
    index = ModelCapabilityIndex.from_config_provider(provider)

    current_in_flight = 0
    max_in_flight = 0

    async def _discover_snapshot(*, generation: int = 1):
        nonlocal current_in_flight, max_in_flight
        current_in_flight += 1
        max_in_flight = max(max_in_flight, current_in_flight)
        await asyncio.sleep(0.05)
        current_in_flight -= 1
        return index.get_snapshot()

    discoverer = Mock()
    discoverer.discover_snapshot = AsyncMock(side_effect=_discover_snapshot)

    controller = ModelCapabilityRefreshController(
        index=index,
        discoverer=discoverer,
        refresh_interval_seconds=0.0,
        failure_backoff_seconds=0.0,
    )

    await asyncio.gather(
        controller.refresh_now(reason="a"),
        controller.refresh_now(reason="b"),
        controller.refresh_now(reason="c"),
    )

    assert max_in_flight == 1
