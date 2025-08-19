import json

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import ChatMessage, ChatRequest

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield GeminiBackend(client=client)


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    return ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content="Hello")]
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": True}
    )
    effective_model = "gemini-1"

    # Gemini returns a streaming JSON array split across chunks
    stream_chunks = [
        b'[{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}',
        b',\n{"candidates": [{"content": {"parts": [{"functionCall": {"name": "attempt_completion", "args": {"result": "ok"}}}], "role": "model"}}]}',
        b',\n{"candidates": [{"finishReason": "TOOL_CALLS"}]}',
        b"]",
    ]
    httpx_mock.add_response(
        url=f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/{effective_model}:streamGenerateContent",
        method="POST",
        stream=httpx.ByteStream(b"".join(stream_chunks)),
        status_code=200,
        headers={"Content-Type": "application/json"},
        match_headers={"x-goog-api-key": "FAKE_KEY"},
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

    # The response is now a StreamingResponseEnvelope
    assert hasattr(response, 'content')
    # Extract the content generator from the envelope
    content_generator = response.content

    chunks = []
    async for chunk in content_generator:
        chunks.append(chunk)

    joined = b"".join(
        [
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in chunks
        ]
    )
    parts = joined.split(b"\n\n")
    first = json.loads(parts[0][len(b"data: ") :])
    assert first["choices"][0]["delta"]["content"] == "Hello"
    # Ensure functionCall chunk yields a later finish with tool_calls
    last_payload = json.loads(parts[-3][len(b"data: ") :])
    assert last_payload["choices"][0]["finish_reason"] in (None, "tool_calls")
    assert parts[-2] == b"data: [DONE]"

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers.get("x-goog-api-key") == "FAKE_KEY"
    sent_payload = json.loads(request.content)
    assert sent_payload["contents"][0]["parts"][0]["text"] == "Hello"
    assert sent_payload.get("stream") is None
