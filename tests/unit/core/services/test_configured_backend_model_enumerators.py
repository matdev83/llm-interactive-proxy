from __future__ import annotations

from unittest.mock import Mock

import pytest
from src.core.config.app_config import BackendConfig
from src.core.services.configured_backend_model_enumerators import (
    CodexAppServerConfiguredModelEnumerator,
    ExplicitConfiguredModelEnumerator,
)


@pytest.mark.asyncio
async def test_explicit_enumerator_returns_only_configured_models() -> None:
    enumerator = ExplicitConfiguredModelEnumerator(
        connector="agy-cli-acp", source="configured"
    )

    result = await enumerator.enumerate(
        "agy-cli-acp.project",
        BackendConfig(
            connector="agy-cli-acp",
            models=["google/gemini-3.5-flash-high"],
        ),
    )

    assert result.models == ("google/gemini-3.5-flash-high",)
    assert result.instance_pinned is True


@pytest.mark.asyncio
async def test_explicit_enumerator_omits_empty_configuration() -> None:
    enumerator = ExplicitConfiguredModelEnumerator(
        connector="gemini-cli-acp", source="configured"
    )

    result = await enumerator.enumerate(
        "gemini-cli-acp.project",
        BackendConfig(connector="gemini-cli-acp"),
    )

    assert result.models == ()
    assert result.status == "unavailable"
    assert result.error_code == "models_not_configured"


@pytest.mark.asyncio
async def test_codex_app_server_uses_only_live_discovered_catalog() -> None:
    catalog = Mock()
    catalog.routable_slugs.return_value = ["gpt-5.6-sol", "gpt-5.6-luna"]
    enumerator = CodexAppServerConfiguredModelEnumerator(
        catalog=catalog,
        catalog_source="discovery",
    )

    result = await enumerator.enumerate(
        "openai-codex-app-server.default",
        BackendConfig(connector="openai-codex-app-server"),
    )

    assert result.models == (
        "openai/auto",
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-luna",
    )


@pytest.mark.asyncio
async def test_codex_app_server_fallback_catalog_advertises_only_auto() -> None:
    catalog = Mock()
    catalog.routable_slugs.return_value = ["stale-model"]
    enumerator = CodexAppServerConfiguredModelEnumerator(
        catalog=catalog,
        catalog_source="fallback",
    )

    result = await enumerator.enumerate(
        "openai-codex-app-server.default",
        BackendConfig(connector="openai-codex-app-server"),
    )

    assert result.models == ("openai/auto",)
