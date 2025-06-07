import pytest
import httpx
import json
from starlette.responses import StreamingResponse
from pytest_httpx import HTTPXMock
import pytest_asyncio

import src.models as models
from src.connectors.gemini import GeminiBackend

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield GeminiBackend(client=client)


@pytest.fixture
def sample_chat_request_data() -> models.ChatCompletionRequest:
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_processed_messages() -> list[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: list[models.ChatMessage],
):
    sample_chat_request_data.stream = True
    effective_model = "gemini-1"

    # Gemini returns a streaming JSON array split across chunks
    stream_chunks = [
        b'[{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}',
        b',\n{"candidates": [{"finishReason": "STOP"}]}',
        b"]",
    ]
    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/{effective_model}:streamGenerateContent?key=FAKE_KEY",
        method="POST",
        stream=httpx.ByteStream(b"".join(stream_chunks)),
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    response = await gemini_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_GEMINI_API_BASE_URL,
        openrouter_headers_provider=None,
        key_name="GEMINI_API_KEY_1",
        api_key="FAKE_KEY",
    )

    assert isinstance(response, StreamingResponse)

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    joined = b"".join(chunks)
    parts = joined.split(b"\n\n")
    first = json.loads(parts[0][len(b"data: ") :])
    assert first["choices"][0]["delta"]["content"] == "Hello"
    assert parts[-2] == b"data: [DONE]"

    request = httpx_mock.get_request()
    assert request is not None
    sent_payload = json.loads(request.content)
    assert sent_payload["contents"][0]["parts"][0]["text"] == "Hello"
    assert sent_payload.get("stream") is None
