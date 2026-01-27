from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from freezegun import freeze_time
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.kiro_oauth_auto.connector import KiroOAuthAutoConnector
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService

# Matches @freeze_time("2026-01-19")
BASE_TIME = 1768780800.0  # 2026-01-19 00:00:00 UTC


def _build_event_stream_message(*, event_type: str, payload_obj: object) -> bytes:
    payload = json.dumps(payload_obj).encode("utf-8")
    header_name = b":event-type"
    header_value = event_type.encode("utf-8")

    headers = bytearray()
    headers.append(len(header_name))
    headers.extend(header_name)
    headers.append(7)  # string
    headers.extend(len(header_value).to_bytes(2, "big"))
    headers.extend(header_value)

    total_length = 12 + len(headers) + len(payload) + 4
    prelude = (
        total_length.to_bytes(4, "big")
        + len(headers).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
    )
    message_crc = (0).to_bytes(4, "big")
    return prelude + bytes(headers) + payload + message_crc


class _Stream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


@freeze_time("2026-01-19")
@pytest.mark.asyncio
async def test_connector_streaming_end_to_end(tmp_path: Path) -> None:
    # Prepare a stored account so initialize() succeeds
    storage_dir = tmp_path / "kiro_oauth_accounts"
    storage = TokenStorageService(storage_path=storage_dir)
    await storage.save_account(
        StoredAccount(
            account_id="acc1",
            auth_method="builderid",
            region="us-east-1",
            access_token="access.test",
            refresh_token="refresh.test",
            client_id="client.test",
            client_secret="secret.test",
            expiry_date=int((BASE_TIME + 3600) * 1000),
        )
    )

    stream_bytes = [
        _build_event_stream_message(
            event_type="assistantResponseEvent",
            payload_obj={"assistantResponseEvent": {"content": "Hello "}},
        ),
        _build_event_stream_message(
            event_type="assistantResponseEvent",
            payload_obj={"assistantResponseEvent": {"content": "world"}},
        ),
        _build_event_stream_message(
            event_type="toolUseEvent",
            payload_obj={
                "toolUseEvent": {
                    "toolUseId": "t1",
                    "name": "do_thing",
                    "input": '{"x":',
                    "stop": False,
                }
            },
        ),
        _build_event_stream_message(
            event_type="toolUseEvent",
            payload_obj={
                "toolUseEvent": {
                    "toolUseId": "t1",
                    "name": "do_thing",
                    "input": "1}",
                    "stop": True,
                }
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/ListAvailableModels?origin=AI_EDITOR&maxResults=50"):
            return httpx.Response(
                200, json={"models": [{"modelId": "claude-sonnet-4.5"}]}
            )
        if url.endswith("/generateAssistantResponse"):
            return httpx.Response(200, stream=_Stream(stream_bytes))
        return httpx.Response(404, json={"error": "not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = AppConfig(
        {
            "backends": {
                "kiro-oauth-auto": {
                    "type": "kiro-oauth-auto",
                    "extra": {"storage_path": str(storage_dir)},
                }
            }
        }
    )
    connector = KiroOAuthAutoConnector(
        client=client, config=config, translation_service=TranslationService()
    )
    await connector.initialize()

    request = CanonicalChatRequest(
        model="claude-sonnet-4.5",
        stream=True,
        session_id="s1",
        messages=[ChatMessage(role="user", content="hi")],
    )
    canonical = ConnectorChatCompletionsRequest(
        request=request,
        processed_messages=list(request.messages),
        effective_model="claude-sonnet-4.5",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=None,
        options={},
    )
    envelope = await connector.chat_completions(canonical)
    assert envelope.media_type.startswith("text/event-stream")
    assert isinstance(envelope, StreamingResponseEnvelope)

    # Consume a few SSE-framed chunks and assert text + tool calls are present
    body = b""
    assert envelope.content is not None
    async for b in envelope.body_iterator:
        body += b

    text = body.decode("utf-8", errors="replace")
    assert "Hello" in text
    assert "world" in text
    assert "tool_calls" in text
    assert "do_thing" in text

    await client.aclose()
