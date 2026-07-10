"""v2 connector inherits the auto-discovered Codex model catalog from v1.

Verifies that ``OpenAICodexV2Connector`` does NOT hardcode model slugs and
instead resolves the catalog per-instance (from DI, else the shipped fallback),
inheriting v1's catalog-driven behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
import pytest_asyncio
from src.connectors.openai_codex.catalog.interfaces import ICodexModelCatalog
from src.connectors.openai_codex.catalog.parser import CodexCatalogParser
from src.connectors.openai_codex_v2 import OpenAICodexV2Connector
from src.core.config.app_config import AppConfig
from tests.unit.connectors.openai_codex.catalog.conftest import make_raw_catalog


@pytest_asyncio.fixture()  # type: ignore[reportUntypedFunctionDecorator]
async def v2_connector() -> AsyncIterator[OpenAICodexV2Connector]:
    from src.core.di.container import ServiceCollection
    from src.core.di.registrations import backend
    from src.core.di.services import set_service_provider

    services = ServiceCollection()
    backend.register(services, AppConfig())
    services.add_instance(
        cast(type, ICodexModelCatalog),
        CodexCatalogParser().parse(make_raw_catalog()),
    )
    set_service_provider(services.build_service_provider())

    client = httpx.AsyncClient()
    instance = OpenAICodexV2Connector(client=client, config=AppConfig())
    try:
        yield instance
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_v2_inherits_discovered_catalog(
    v2_connector: OpenAICodexV2Connector,
) -> None:
    """v2 resolves the catalog from DI (no hardcoded class attrs)."""
    catalog = v2_connector._catalog
    assert catalog.routable_slugs() == ("gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.5")
    # Inherited instance properties delegate to the catalog (not stale class attrs).
    assert catalog.routable_slugs() == v2_connector.SUPPORTED_CODEX_MODELS
    assert catalog.reasoning_effort_order == v2_connector.REASONING_EFFORT_LEVELS
    assert v2_connector.DEFAULT_REASONING_EFFORT == "medium"
    # v2 advertises the discovered slugs (vendor-prefixed).
    assert v2_connector.get_available_models() == [
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.5",
    ]


@pytest.mark.asyncio
async def test_v2_is_codex_model_uses_catalog(
    v2_connector: OpenAICodexV2Connector,
) -> None:
    assert v2_connector._is_codex_model("gpt-5.6-sol") is True
    assert v2_connector._is_codex_model("gpt-5.5") is True
    # Legacy slug absent from the discovered catalog is not routable.
    assert v2_connector._is_codex_model("gpt-5.1-codex") is False
