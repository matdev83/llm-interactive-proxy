"""Tests for ``CodexModelCatalogProvider`` — discovery -> fallback orchestration."""

from __future__ import annotations

import pytest
from src.connectors.openai_codex.catalog.config import CodexModelCatalogConfig
from src.connectors.openai_codex.catalog.provider import CodexModelCatalogProvider

from tests.unit.connectors.openai_codex.catalog.conftest import (
    FakeDiscovery,
    FakeFallback,
    sentinel_catalog,
)


@pytest.fixture()
def sentinel_d():
    return sentinel_catalog()


@pytest.fixture()
def sentinel_f():
    return sentinel_catalog()


class TestProviderDiscoverySuccess:
    @pytest.mark.asyncio
    async def test_load_uses_discovered_catalog(self, sentinel_d, sentinel_f) -> None:
        discovery = FakeDiscovery(result=sentinel_d)
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=True),
            fallback_loader=fallback,
            discovery_service=discovery,
        )
        await provider.load()

        assert provider.get_catalog() is sentinel_d
        assert fallback.calls == 0

    @pytest.mark.asyncio
    async def test_load_caches_result(self, sentinel_d, sentinel_f) -> None:
        discovery = FakeDiscovery(result=sentinel_d)
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=True),
            fallback_loader=fallback,
            discovery_service=discovery,
        )
        await provider.load()
        await provider.load()

        assert discovery.calls == 1


class TestProviderFallback:
    @pytest.mark.asyncio
    async def test_discovery_none_falls_back(self, sentinel_d, sentinel_f) -> None:
        discovery = FakeDiscovery(result=None)
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=True),
            fallback_loader=fallback,
            discovery_service=discovery,
        )
        await provider.load()

        assert provider.get_catalog() is sentinel_f
        assert fallback.calls == 1

    @pytest.mark.asyncio
    async def test_discovery_raises_falls_back(self, sentinel_d, sentinel_f) -> None:
        discovery = FakeDiscovery(raises=RuntimeError("boom"))
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=True),
            fallback_loader=fallback,
            discovery_service=discovery,
        )
        await provider.load()

        assert provider.get_catalog() is sentinel_f
        assert fallback.calls == 1

    @pytest.mark.asyncio
    async def test_discovery_disabled_falls_back_without_calling_discovery(
        self, sentinel_d, sentinel_f
    ) -> None:
        discovery = FakeDiscovery(result=sentinel_d)
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=False),
            fallback_loader=fallback,
            discovery_service=discovery,
        )
        await provider.load()

        assert provider.get_catalog() is sentinel_f
        assert discovery.calls == 0
        assert fallback.calls == 1


class TestProviderGetCatalogContract:
    @pytest.mark.asyncio
    async def test_get_catalog_before_load_raises(self, sentinel_f) -> None:
        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(),
            fallback_loader=FakeFallback(result=sentinel_f),
            discovery_service=FakeDiscovery(),
        )
        with pytest.raises(RuntimeError):
            provider.get_catalog()


class TestProviderLoadFallbackOnly:
    @pytest.mark.asyncio
    async def test_load_fallback_only_does_not_call_discovery(
        self, sentinel_d, sentinel_f
    ) -> None:
        discovery = FakeDiscovery(result=sentinel_d)
        fallback = FakeFallback(result=sentinel_f)

        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(discovery_enabled=True),
            fallback_loader=fallback,
            discovery_service=discovery,
        )

        assert provider.load_fallback_only() is sentinel_f
        assert discovery.calls == 0
        assert fallback.calls == 1

    @pytest.mark.asyncio
    async def test_load_fallback_only_does_not_populate_get_catalog(
        self, sentinel_d, sentinel_f
    ) -> None:
        """``load_fallback_only`` is a standalone escape hatch; it must not
        satisfy ``get_catalog()`` which requires an explicit ``load()``."""
        provider = CodexModelCatalogProvider(
            config=CodexModelCatalogConfig(),
            fallback_loader=FakeFallback(result=sentinel_f),
            discovery_service=FakeDiscovery(result=sentinel_d),
        )
        provider.load_fallback_only()
        with pytest.raises(RuntimeError):
            provider.get_catalog()
