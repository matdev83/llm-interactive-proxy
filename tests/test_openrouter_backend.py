import pytest
import httpx
from typing import AsyncIterator # Import AsyncIterator

from backends.openrouter import OpenRouterBackend
from models import ChatMessage, ChatCompletionRequest


class MockStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_chat_completion_non_stream():
    async def handler(request: httpx.Request):
        import json

        data = json.loads(request.content.decode())
        assert data["model"] == "test-model"
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OpenRouterBackend(
            client,
            api_key="key",
            api_base_url="https://example.com",
            app_site_url="http://localhost",
            app_title="Test",
        )
        req = ChatCompletionRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            stream=False,
        )
        resp = await backend.chat_completion(req)
        assert resp == {"choices": []}


@pytest.mark.asyncio
async def test_chat_completion_stream():
    async def handler(request: httpx.Request):
        stream = MockStream([b"a", b"b"])
        return httpx.Response(200, stream=stream)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OpenRouterBackend(
            client,
            api_key="key",
            api_base_url="https://example.com",
            app_site_url="http://localhost",
            app_title="Test",
        )
        req = ChatCompletionRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        iterator: AsyncIterator[bytes] = await backend.chat_completion(req, stream=True)
        chunks = [c async for c in iterator]
        assert chunks == [b"a", b"b"]


@pytest.mark.asyncio
async def test_list_models():
    async def handler(request: httpx.Request):
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OpenRouterBackend(
            client,
            api_key="key",
            api_base_url="https://example.com",
            app_site_url="http://localhost",
            app_title="Test",
        )
        resp = await backend.list_models()
        assert resp == {"data": []}
