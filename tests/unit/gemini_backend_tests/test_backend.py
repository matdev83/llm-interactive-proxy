import json
import pytest
import httpx
from pytest_httpx import HTTPXMock
import pytest_asyncio

import src.models as models
from src.backends.gemini import GeminiBackend

TEST_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@pytest_asyncio.fixture
async def backend():
    async with httpx.AsyncClient() as client:
        yield GeminiBackend(client, api_keys=["AI" + "z" * 30])


@pytest.fixture
def sample_request() -> models.ChatCompletionRequest:
    return models.ChatCompletionRequest(
        model="gemini-pro",
        messages=[models.ChatMessage(role="user", content="Hello")],
        stream=False,
    )


@pytest.mark.asyncio
async def test_chat_completion_non_streaming_success(backend: GeminiBackend, httpx_mock: HTTPXMock, sample_request):
    expected_response = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    httpx_mock.add_response(
        url=f"{TEST_BASE_URL}/models/gemini-pro:generateContent?key={'AI'+'z'*30}",
        method="POST",
        json=expected_response,
        headers={"X-Token-Usage": "5"},
    )

    resp = await backend.chat_completion(sample_request)

    assert resp["data"] == expected_response
    assert resp["headers"]["x-token-usage"] == "5"

    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    assert payload["contents"][0]["parts"][0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_chat_completion_streaming_success(backend: GeminiBackend, httpx_mock: HTTPXMock, sample_request):
    sample_request.stream = True
    stream_chunks = [b"chunk1", b"chunk2"]
    httpx_mock.add_response(
        url=f"{TEST_BASE_URL}/models/gemini-pro:streamGenerateContent?key={'AI'+'z'*30}",
        method="POST",
        stream=httpx.ByteStream(b"".join(stream_chunks)),
        headers={"Content-Type": "application/json"},
    )

    iterator = await backend.chat_completion(sample_request, stream=True)
    data = b""
    async for chunk in iterator:
        data += chunk
    assert data == b"".join(stream_chunks)


@pytest.mark.asyncio
async def test_chat_completion_http_error(backend: GeminiBackend, httpx_mock: HTTPXMock, sample_request):
    httpx_mock.add_response(
        url=f"{TEST_BASE_URL}/models/gemini-pro:generateContent?key={'AI'+'z'*30}",
        method="POST",
        status_code=400,
        json={"error": "bad"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await backend.chat_completion(sample_request)


@pytest.mark.asyncio
async def test_list_models_success(backend: GeminiBackend, httpx_mock: HTTPXMock):
    models_resp = {"models": ["a", "b"]}
    httpx_mock.add_response(
        url=f"{TEST_BASE_URL}/models?key={'AI'+'z'*30}",
        method="GET",
        json=models_resp,
        headers={"X-Token-Usage": "1"},
    )
    resp = await backend.list_models()
    assert resp["data"] == models_resp
    assert resp["headers"]["x-token-usage"] == "1"
