from __future__ import annotations
import asyncio

import httpx

from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig
from src.core.config.config_loader import get_openrouter_headers
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import HeaderConfig, HeaderOverrideMode


def test_openrouter_headers_provider_accepts_config_dict() -> None:
    """Ensure OpenRouter backend adapts config-based header providers."""

    async def run_test() -> dict[str, str]:
        identity = AppIdentityConfig(
            url=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="https://example.invalid/test",
            ),
            title=HeaderConfig(
                mode=HeaderOverrideMode.DEFAULT,
                default_value="ExampleProxy",
            ),
        )
        config = AppConfig(identity=identity)

        async with httpx.AsyncClient() as client:
            backend = OpenRouterBackend(client=client, config=config)
            await backend.initialize(
                api_key="integration-key",
                key_name="openrouter",
                openrouter_headers_provider=get_openrouter_headers,
            )
            return backend.get_headers()

    headers = asyncio.run(run_test())

    assert headers["Authorization"] == "Bearer integration-key"
    assert headers["HTTP-Referer"] == "https://example.invalid/test"
    assert headers["X-Title"] == "ExampleProxy"
