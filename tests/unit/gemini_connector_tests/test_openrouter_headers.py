import asyncio

import httpx
from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import ChatMessage, ChatRequest

from tests.unit.gemini_connector_tests.helpers import gemini_connector_request

OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"


def test_openrouter_headers_provider_used() -> None:
    async def run_test() -> None:
        seen_headers: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update({k.lower(): v for k, v in request.headers.items()})
            assert str(request.url) == (
                f"{OPENROUTER_API_BASE_URL}/v1beta/models/gemini-1:generateContent"
            )
            return httpx.Response(
                status_code=200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "Hi"}]}},
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 2,
                    },
                },
            )

        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(transport=transport) as client:
            from src.core.config.app_config import AppConfig
            from src.core.services.translation_service import TranslationService

            backend = GeminiBackend(
                client=client,
                config=AppConfig(),
                translation_service=TranslationService(),
            )

            chat_request = ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="Hello")],
                stream=False,
            )
            processed_messages = [ChatMessage(role="user", content="Hello")]

            provider_calls: list[tuple[object, str]] = []

            def provider(arg: object, api_key: str) -> dict[str, str]:
                provider_calls.append((arg, api_key))
                if isinstance(arg, str):
                    raise TypeError
                assert isinstance(arg, dict)
                assert "app_site_url" in arg
                assert "app_x_title" in arg
                return {
                    "Authorization": f"Bearer provided-{api_key}",
                    "HTTP-Referer": "provided-ref",
                }

            backend.openrouter_headers_provider = provider

            await backend.chat_completions(
                gemini_connector_request(
                    chat_request,
                    processed_messages=processed_messages,
                    effective_model="models/gemini-1",
                    options={
                        "openrouter_api_base_url": OPENROUTER_API_BASE_URL,
                        "key_name": "gemini",
                        "api_key": "OPENROUTER_KEY",
                    },
                )
            )

            assert len(provider_calls) == 2
            assert isinstance(provider_calls[0][0], str)
            assert isinstance(provider_calls[1][0], dict)

        assert seen_headers["authorization"] == "Bearer provided-OPENROUTER_KEY"
        assert seen_headers["http-referer"] == "provided-ref"
        assert seen_headers["content-type"].startswith("application/json")
        assert seen_headers["x-llmproxy-loop-guard"] == "1"

    asyncio.run(run_test())
