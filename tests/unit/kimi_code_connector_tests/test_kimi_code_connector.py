from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
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
        value = self._chunks[self._idx]
        self._idx += 1
        return value


class MockStreamingResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        chunks: list[bytes] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks or []
        self.headers = headers or {}
        self._closed = False

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        return AsyncIterBytes(self._chunks)

    async def aread(self) -> bytes:
        return b"".join(self._chunks)

    async def aclose(self) -> None:
        self._closed = True


@pytest.mark.asyncio
async def test_kimi_stream_mirrors_reasoning_content_to_content() -> None:
    """Ensure streamed reasoning_content is also visible as content."""

    raw_event = {
        "id": "chatcmpl_test",
        "model": "kimi-for-coding",
        "created": 123,
        "choices": [
            {
                "index": 0,
                "delta": {"content": "", "reasoning_content": "Hello"},
                "finish_reason": None,
            }
        ],
    }

    chunk = f"data: {json.dumps(raw_event)}\n\n".encode()
    done = b"data: [DONE]\n\n"

    client = AsyncMock()
    client.build_request.side_effect = lambda *args, **kwargs: httpx.Request(
        *args, **kwargs
    )
    client.send.return_value = MockStreamingResponse(chunks=[chunk, done])

    translation_service = MagicMock()
    connector = KimiCodeConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    connector.api_key = "test"

    async def _fake_prepare_payload(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"model": "kimi/kimi-for-coding", "messages": [], "stream": True}

    connector._prepare_payload = _fake_prepare_payload  # type: ignore[method-assign]

    request = CanonicalChatRequest(
        model="kimi/kimi-for-coding",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    out_parts: list[bytes] = []
    async for part in connector.stream_completion(request):
        if isinstance(part, bytes):
            out_parts.append(part)
        elif isinstance(part, bytearray):
            out_parts.append(bytes(part))
        elif isinstance(part, str):
            out_parts.append(part.encode("utf-8"))
        else:  # pragma: no cover - defensive
            raise AssertionError(f"Unexpected chunk type: {type(part).__name__}")

    out = b"".join(out_parts)
    out_text = out.decode("utf-8", errors="replace")

    # After mirroring, delta.content should include the reasoning text.
    assert '"content": "Hello"' in out_text
    assert "data: [DONE]" in out_text


@pytest.mark.asyncio
async def test_kimi_non_streaming_mirrors_reasoning_to_content() -> None:
    """Ensure non-streaming responses mirror reasoning into message.content."""

    response_json = {
        "id": "chatcmpl_test",
        "model": "kimi-for-coding",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "reasoning": "Hi"},
                "finish_reason": "stop",
            }
        ],
    }

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = response_json
    fake_response.headers = {}

    client = AsyncMock()
    client.post.return_value = fake_response

    captured: dict[str, Any] = {}

    class DummyDomainResponse:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data
            self.usage = None

        def model_dump(self) -> dict[str, Any]:
            return self._data

    translation_service = MagicMock()

    def _capture_to_domain_response(
        data: dict[str, Any], _fmt: str
    ) -> DummyDomainResponse:
        captured["data"] = data
        return DummyDomainResponse(data)

    translation_service.to_domain_response.side_effect = _capture_to_domain_response

    connector = KimiCodeConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    connector.api_key = "test"

    await connector._handle_non_streaming_response(
        url="https://api.kimi.com/coding/v1/chat/completions",
        payload={"model": "kimi-for-coding"},
        headers={"Authorization": "Bearer test"},
        session_id="",
        context=None,
    )

    assert captured
    mirrored = captured["data"]["choices"][0]["message"]["content"]
    assert mirrored == "Hi"


def test_kimi_headers_include_kilo_fingerprint_and_no_loop_guard() -> None:
    client = AsyncMock()
    translation_service = MagicMock()
    connector = KimiCodeConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )
    connector.api_key = "test"

    headers = connector.get_headers()
    assert headers.get("Authorization") == "Bearer test"
    assert headers.get("User-Agent", "").startswith("Kilo-Code/")
    assert headers.get("Referer") == "https://kilocode.ai"
    assert headers.get("Origin") == "https://kilocode.ai"
    assert headers.get("HTTP-Referer") == "https://kilocode.ai"
    assert headers.get("X-Title") == "Kilo Code"
    assert "x-llmproxy-loop-guard" not in {k.lower() for k in headers}


@pytest.mark.asyncio
async def test_kimi_prepare_payload_strips_vendor_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    translation_service = MagicMock()
    connector = KimiCodeConnector(
        client=client,
        config=AppConfig(),
        translation_service=translation_service,
    )

    async def _base_prepare_payload(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"model": "kimi/kimi-for-coding"}

    from src.connectors.openai import OpenAIConnector

    monkeypatch.setattr(OpenAIConnector, "_prepare_payload", _base_prepare_payload)

    payload = await connector._prepare_payload(  # type: ignore[misc]
        CanonicalChatRequest(
            model="kimi/kimi-for-coding",
            messages=[ChatMessage(role="user", content="hi")],
        ),
        [ChatMessage(role="user", content="hi")],
        "kimi/kimi-for-coding",
        context=None,
    )
    assert payload["model"] == "kimi-for-coding"
