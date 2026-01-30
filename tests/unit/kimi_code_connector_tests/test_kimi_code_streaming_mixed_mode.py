from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.kimi_code import KimiCodeConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


class AsyncIterBytes:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self._idx = 0

    def __aiter__(self) -> AsyncIterBytes:
        return self

    async def __anext__(self) -> bytes:
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        val = self._chunks[self._idx]
        self._idx += 1
        return val


class MockStreamingResponse:
    def __init__(self, chunks: list[bytes], status_code: int = 200) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers: dict[str, str] = {}

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        return AsyncIterBytes(self._chunks)

    async def aread(self) -> bytes:
        return b"".join(self._chunks)

    async def aclose(self) -> None:
        return None


def _make_sse_event(delta: dict) -> bytes:
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "kimi-for-coding",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


@pytest.mark.asyncio
async def test_kimi_streaming_mixed_delta_and_accumulated_content_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This reproduces the pattern observed in the live CBOR capture:
    # deltas: "I", " have", " found" then an accumulated chunk "I have found".

    chunks = [
        _make_sse_event({"content": "I"}),
        _make_sse_event({"content": " have"}),
        _make_sse_event({"content": " found"}),
        _make_sse_event({"content": "I have found"}),
        b"data: [DONE]\n\n",
    ]

    client = AsyncMock()
    client.build_request = MagicMock(return_value=object())
    client.send = AsyncMock(return_value=MockStreamingResponse(chunks))

    connector = KimiCodeConnector(
        client=client,
        config=AppConfig(),
        translation_service=MagicMock(),
    )
    connector.api_key = "test"

    async def _base_prepare_payload(*_args, **_kwargs):
        return {"model": "kimi/kimi-for-coding", "messages": []}

    from src.connectors.openai import OpenAIConnector

    monkeypatch.setattr(OpenAIConnector, "_prepare_payload", _base_prepare_payload)

    req = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hi")],
    )

    out_bytes = b""
    async for part in connector.stream_completion(req):
        assert isinstance(part, bytes | bytearray)
        out_bytes += bytes(part)

    # Parse SSE and reconstruct assistant content by concatenating delta.content
    text_parts: list[str] = []
    for event in out_bytes.decode("utf-8", errors="replace").split("\n\n"):
        event = event.strip()
        if not event or not event.startswith("data:"):
            continue
        data_str = event[5:].strip()
        if data_str == "[DONE]":
            continue
        data = json.loads(data_str)
        delta = data["choices"][0]["delta"]
        if "content" in delta:
            text_parts.append(delta["content"])

    assert "".join(text_parts) == "I have found"
    # And we should never forward the accumulated chunk as full text.
    assert "I have foundI have found" not in out_bytes.decode("utf-8", errors="replace")
