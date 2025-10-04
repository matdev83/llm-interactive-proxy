from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import HeaderConfig, HeaderOverrideMode


def mock_headers_provider(_: str, api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"id": "ok"})


@pytest.fixture
def backend_with_transport() -> Iterator[tuple[OpenRouterBackend, RecordingTransport]]:
    transport = RecordingTransport()
    client = httpx.AsyncClient(transport=transport)
    config = AppConfig()
    backend = OpenRouterBackend(client=client, config=config)

    asyncio.run(
        backend.initialize(
            api_key="init-key",
            key_name="init",
            openrouter_headers_provider=mock_headers_provider,
        )
    )

    try:
        yield backend, transport
    finally:
        asyncio.run(client.aclose())


def test_identity_headers_forwarded(
    backend_with_transport: tuple[OpenRouterBackend, RecordingTransport]
) -> None:
    backend, transport = backend_with_transport

    identity = AppIdentityConfig(
        title=HeaderConfig(
            mode=HeaderOverrideMode.DEFAULT,
            default_value="Custom Title",
            passthrough_name="x-title",
        ),
        url=HeaderConfig(
            mode=HeaderOverrideMode.DEFAULT,
            default_value="https://example.invalid",
            passthrough_name="http-referer",
        ),
        user_agent=HeaderConfig(
            mode=HeaderOverrideMode.DEFAULT,
            default_value="CustomAgent/1.0",
            passthrough_name="user-agent",
        ),
    )

    request = ChatRequest(
        model="openai/gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    asyncio.run(
        backend.chat_completions(
            request_data=request,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="openai/gpt-4",
            openrouter_api_base_url="https://openrouter.ai/api/v1",
            openrouter_headers_provider=mock_headers_provider,
            key_name="call-key",
            api_key="call-api-key",
            identity=identity,
        )
    )

    assert transport.requests, "Expected OpenRouter backend to issue an HTTP request"
    sent_headers = transport.requests[0].headers

    assert sent_headers.get("Authorization") == "Bearer call-api-key"
    assert sent_headers.get("X-Title") == "Custom Title"
    assert sent_headers.get("HTTP-Referer") == "https://example.invalid"
    assert sent_headers.get("User-Agent") == "CustomAgent/1.0"
