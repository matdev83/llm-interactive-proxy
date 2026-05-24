from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig, get_openrouter_headers
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import HeaderConfig, HeaderOverrideMode

from tests.unit.openrouter_connector_tests.helpers import (
    openrouter_connector_chat_request,
)


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
            backend = OpenRouterBackend(
                client=client, config=config, translation_service=MagicMock()
            )
            await backend.initialize(
                api_key="integration-key",
                key_name="openrouter",
                openrouter_headers_provider=get_openrouter_headers,
            )
            return cast(dict[str, str], backend.get_headers())

    headers = asyncio.run(run_test())

    assert headers["Authorization"] == "Bearer integration-key"
    assert headers["HTTP-Referer"] == "https://example.invalid/test"
    assert headers["X-Title"] == "ExampleProxy"


@pytest.mark.asyncio
@pytest.mark.httpx_mock()
async def test_chat_completions_supports_config_dict_headers(
    httpx_mock: HTTPXMock,
) -> None:
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
    translation_service_mock = MagicMock()

    async with httpx.AsyncClient() as client:
        backend = OpenRouterBackend(
            client=client, config=config, translation_service=translation_service_mock
        )
        await backend.initialize(
            api_key="integration-key",
            key_name="openrouter",
            openrouter_headers_provider=get_openrouter_headers,
        )

        request_data = ChatRequest(
            model="openai/gpt-3.5-turbo",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )

        translation_service_mock.from_domain_request.return_value = {
            "model": "openai/gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        httpx_mock.add_response(json={"id": "ok"}, status_code=200)

        await backend.chat_completions(
            openrouter_connector_chat_request(
                request_data,
                processed_messages=[ChatMessage(role="user", content="Hello")],
                effective_model="openai/gpt-3.5-turbo",
                key_name="openrouter",
                api_key="integration-key",
            )
        )

    requests = httpx_mock.get_requests()
    assert len(requests) > 0
    req = requests[0]
    assert req is not None
    assert req.headers.get("Authorization") == "Bearer integration-key"
    assert req.headers.get("HTTP-Referer") == "https://example.invalid/test"
    assert req.headers.get("X-Title") == "ExampleProxy"
