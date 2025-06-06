import json
import httpx
from pytest_httpx import HTTPXMock
import pytest
import pytest_asyncio

import src.models as models
from src.connectors.gemini import GeminiBackend

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"

@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield GeminiBackend(client=client)


@pytest.mark.asyncio
async def test_text_part_type_removed(gemini_backend: GeminiBackend, httpx_mock: HTTPXMock):
    request_data = models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content=[models.MessageContentPartText(type="text", text="Hi")])],
    )
    processed_messages = [
        models.ChatMessage(role="user", content=[models.MessageContentPartText(type="text", text="Hi")])
    ]
    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/test-model:generateContent?key=FAKE_KEY",
        method="POST",
        json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    await gemini_backend.chat_completions(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model="test-model",
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        openrouter_headers_provider=None,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    request = httpx_mock.get_request()
    assert request is not None
    payload = json.loads(request.content)
    part = payload["contents"][0]["parts"][0]
    assert part == {"text": "Hi"}


@pytest.mark.asyncio
async def test_system_message_filtered(gemini_backend: GeminiBackend, httpx_mock: HTTPXMock):
    request_data = models.ChatCompletionRequest(
        model="test-model",
        messages=[
            models.ChatMessage(role="system", content="You are Roo"),
            models.ChatMessage(role="user", content="Hello"),
        ],
    )
    processed_messages = [
        models.ChatMessage(role="system", content="You are Roo"),
        models.ChatMessage(role="user", content="Hello"),
    ]
    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/test-model:generateContent?key=FAKE_KEY",
        method="POST",
        json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    await gemini_backend.chat_completions(
        request_data=request_data,
        processed_messages=processed_messages,
        effective_model="test-model",
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        openrouter_headers_provider=None,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    request = httpx_mock.get_request()
    assert request is not None
    payload = json.loads(request.content)
    assert len(payload["contents"]) == 1
    assert payload["contents"][0]["role"] == "user"
