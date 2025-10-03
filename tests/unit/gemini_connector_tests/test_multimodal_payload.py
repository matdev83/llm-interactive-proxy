import json

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
)

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        yield GeminiBackend(
            client=client, config=config, translation_service=TranslationService()
        )


@pytest.mark.asyncio
async def test_multimodal_data_url_converts_to_inline_data(
    gemini_backend: GeminiBackend, httpx_mock: HTTPXMock
):
    request_data = ChatRequest(
        model="models/gemini-pro",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(type="text", text="Describe this"),
                    MessageContentPartImage(
                        type="image_url",
                        image_url=ImageURL(
                            url="data:image/png;base64,aGVsbG8=", detail=None
                        ),
                    ),
                ],
            )
        ],
    )

    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/gemini-pro:generateContent",
        method="POST",
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": "ok"}], "role": "model"},
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 1,
                "totalTokenCount": 2,
            },
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
        match_headers={"x-goog-api-key": "FAKE_KEY"},
    )

    await gemini_backend.chat_completions(
        request_data=request_data,
        processed_messages=request_data.messages,
        effective_model="gemini:models/gemini-pro",
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    request = httpx_mock.get_request()
    assert request is not None
    payload = json.loads(request.content)
    parts = payload["contents"][0]["parts"]
    assert {"text": "Describe this"} in parts
    assert any("inlineData" in p for p in parts), parts
    inline = next(p["inlineData"] for p in parts if "inlineData" in p)
    assert inline["mimeType"] == "image/png"
    assert inline["data"] == "aGVsbG8="


@pytest.mark.asyncio
async def test_multimodal_http_url_converts_to_file_data(
    gemini_backend: GeminiBackend, httpx_mock: HTTPXMock
):
    request_data = ChatRequest(
        model="gemini-pro",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(type="text", text="Describe this"),
                    MessageContentPartImage(
                        type="image_url",
                        image_url=ImageURL(
                            url="http://example.com/cat.jpg", detail=None
                        ),
                    ),
                ],
            )
        ],
    )

    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/gemini-pro:generateContent",
        method="POST",
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": "ok"}], "role": "model"},
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 1,
                "totalTokenCount": 2,
            },
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
        match_headers={"x-goog-api-key": "FAKE_KEY"},
    )

    await gemini_backend.chat_completions(
        request_data=request_data,
        processed_messages=request_data.messages,
        effective_model="gemini:gemini-pro",
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    request = httpx_mock.get_request()
    assert request is not None
    payload = json.loads(request.content)
    parts = payload["contents"][0]["parts"]
    assert {"text": "Describe this"} in parts
    assert any("fileData" in p for p in parts), parts
    file_data = next(p["fileData"] for p in parts if "fileData" in p)
    assert file_data["fileUri"] == "http://example.com/cat.jpg"
