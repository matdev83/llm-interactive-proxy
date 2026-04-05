from __future__ import annotations

from typing import Any

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.nvidia import NvidiaConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService


class _RecordingWireCapture:
    """Minimal wire capture double that records boundary capture calls."""

    def __init__(self) -> None:
        self.outbound_calls: list[dict[str, Any]] = []
        self.inbound_calls: list[dict[str, Any]] = []

    def enabled(self) -> bool:
        return True

    async def capture_outbound_request(self, **kwargs: Any) -> None:
        self.outbound_calls.append(kwargs)

    async def capture_inbound_response(self, **kwargs: Any) -> None:
        self.inbound_calls.append(kwargs)


class _RecordingServiceProvider:
    """Service-provider shim for the wire-boundary capture helper."""

    def __init__(self, wire_capture: _RecordingWireCapture) -> None:
        self._wire_capture = wire_capture

    def get_service(self, _service_type: Any) -> _RecordingWireCapture:
        return self._wire_capture


@pytest.mark.asyncio
async def test_nvidia_dedicated_http11_client_boundary_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NVIDIA's dedicated client must still emit HTTP boundary capture for proxied chat."""

    wire_capture = _RecordingWireCapture()
    provider = _RecordingServiceProvider(wire_capture)
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture.get_service_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._is_cbor_wire_capture",
        lambda _wire_capture: True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "meta/llama3-70b"}]})
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-nvidia-boundary",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "meta/llama3-70b",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "boundary capture ok",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    shared_client = httpx.AsyncClient(http2=True, transport=transport, trust_env=False)
    connector = NvidiaConnector(
        client=shared_client,
        config=AppConfig(),
        translation_service=TranslationService(),
    )
    envelope: ResponseEnvelope | StreamingResponseEnvelope | None = None

    try:
        await connector.initialize(api_key="test-nvidia-key")
        connector.disable_health_check()

        assert connector.client is not shared_client
        assert connector._nvidia_http11_client is connector.client

        request = CanonicalChatRequest(
            model="meta/llama3-70b",
            messages=[ChatMessage(role="user", content="ping")],
            stream=False,
        )
        context = ConnectorRequestContext(
            request_id="req-nvidia-boundary",
            session_id="sess-nvidia-boundary",
            client_host="127.0.0.1",
            extensions={},
        )
        connector_request = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=list(request.messages),
            effective_model=request.model,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=context,
            options={},
        )

        envelope = await connector.chat_completions(connector_request)
    finally:
        await connector.close()
        await shared_client.aclose()

    assert envelope is not None
    assert isinstance(envelope, ResponseEnvelope)
    body = envelope.content
    assert isinstance(body, dict)
    assert body["choices"][0]["message"]["content"] == "boundary capture ok"

    assert len(wire_capture.outbound_calls) == 1
    assert len(wire_capture.inbound_calls) == 1

    outbound = wire_capture.outbound_calls[0]
    assert outbound["backend"] == "nvidia"
    assert outbound["model"] == "meta/llama3-70b"
    assert outbound["key_name"] == "nvidia"
    assert outbound["capture_metadata"]["transport"] == "http"
    assert outbound["capture_metadata"]["protocol_event"] == "request"
    assert outbound["capture_metadata"]["http_method"] == "POST"
    assert outbound["request_payload"].startswith(
        b"POST /v1/chat/completions HTTP/1.1\r\n"
    )

    inbound = wire_capture.inbound_calls[0]
    assert inbound["backend"] == "nvidia"
    assert inbound["model"] == "meta/llama3-70b"
    assert inbound["key_name"] == "nvidia"
    assert inbound["capture_metadata"]["transport"] == "http"
    assert inbound["capture_metadata"]["protocol_event"] == "response"
    assert inbound["capture_metadata"]["status_code"] == 200
    assert inbound["response_content"].startswith(b"HTTP/1.1 200 OK\r\n")
