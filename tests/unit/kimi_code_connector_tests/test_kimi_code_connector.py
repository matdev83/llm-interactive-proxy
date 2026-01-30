from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
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
    # Ensure VENDOR_PREFIX is set for this test
    connector.VENDOR_PREFIX = "kimi"

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
