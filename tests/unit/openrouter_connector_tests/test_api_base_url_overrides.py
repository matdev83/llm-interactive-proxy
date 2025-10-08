import asyncio

import httpx

from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest


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


def test_initialize_accepts_generic_api_base_url() -> None:
    transport = RecordingTransport()
    client = httpx.AsyncClient(transport=transport)
    config = AppConfig()
    backend = OpenRouterBackend(client=client, config=config)

    try:
        asyncio.run(
            backend.initialize(
                api_key="init-key",
                key_name="init",
                openrouter_headers_provider=mock_headers_provider,
                api_base_url="https://alt.invalid/api/v1",
            )
        )
        assert backend.api_base_url == "https://alt.invalid/api/v1"
    finally:
        asyncio.run(client.aclose())


def test_call_allows_generic_api_base_url_override() -> None:
    transport = RecordingTransport()
    client = httpx.AsyncClient(transport=transport)
    config = AppConfig()
    backend = OpenRouterBackend(client=client, config=config)

    try:
        asyncio.run(
            backend.initialize(
                api_key="init-key",
                key_name="init",
                openrouter_headers_provider=mock_headers_provider,
            )
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
                openrouter_headers_provider=mock_headers_provider,
                key_name="call-key",
                api_key="call-api-key",
                api_base_url="https://override.invalid/api/v1",
            )
        )

        assert transport.requests, "Expected OpenRouter backend to issue an HTTP request"
        requested_url = str(transport.requests[0].url)
        assert requested_url.startswith(
            "https://override.invalid/api/v1/chat/completions"
        )
    finally:
        asyncio.run(client.aclose())
