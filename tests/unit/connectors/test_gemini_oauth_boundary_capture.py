from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from src.connectors.contracts import ConnectorRequestContext
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.streaming_executor import StreamingExecutor


class CborWireCaptureService:
    def __init__(self) -> None:
        self.outbound_requests: list[dict[str, Any]] = []
        self.inbound_responses: list[dict[str, Any]] = []

    def enabled(self) -> bool:
        return True

    async def capture_outbound_request(self, **kwargs: Any) -> None:
        self.outbound_requests.append(kwargs)

    async def capture_inbound_response(self, **kwargs: Any) -> None:
        self.inbound_responses.append(kwargs)


class _AuthSessionDouble:
    def __init__(self, response: requests.Response) -> None:
        self.headers = {
            "Authorization": "Bearer oauth-access-token",
            "User-Agent": "antigravity/1.11.5 windows/amd64",
        }
        self._response = response
        self._session = requests.Session()

    def prepare_request(self, request: requests.Request) -> requests.PreparedRequest:
        return self._session.prepare_request(request)

    def merge_environment_settings(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self._response.request = request
        return self._response


def _build_streaming_response() -> requests.Response:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.reason = "OK"
    response.headers = {"content-type": "text/event-stream"}
    response._content = False
    response.close = MagicMock()

    def iter_content(
        chunk_size: int = 4096, decode_unicode: bool = False
    ) -> Iterator[bytes]:
        del chunk_size, decode_unicode
        yield (
            b'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]},'
            b'"finishReason":"STOP"}]}\n\n'
        )

    response.iter_content = iter_content
    return response


@pytest.mark.asyncio
async def test_streaming_executor_captures_requests_based_oauth_boundary_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    translation_service = MagicMock()
    translation_service.to_domain_stream_chunk.side_effect = lambda **kwargs: {
        "id": "chatcmpl-oauth-boundary",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "hello"},
                "finish_reason": "stop",
            }
        ],
    }

    response = _build_streaming_response()
    prepared = PreparedChatRequest(
        auth_session=_AuthSessionDouble(response),
        project_id="project-antigravity",
        canonical_request=None,
        code_assist_request={
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}]
        },
        prompt_tokens_estimate=0,
        effective_model="gemini-2.5-pro",
        session_id="sess-oauth-boundary",
        signature_session_id="sess-oauth-boundary",
        build_request_body=lambda: {
            "requestId": "req-antigravity",
            "userAgent": "antigravity/1.11.5 windows/amd64",
            "requestType": "MODEL",
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        },
    )
    context = ConnectorRequestContext(
        request_id="req-oauth-boundary",
        session_id="sess-oauth-boundary",
        client_host="127.0.0.1",
        extensions={},
    )

    executor = StreamingExecutor(
        translation_service=translation_service,
        backend_type="antigravity-oauth",
    )

    chunks = [
        chunk
        async for chunk in executor.execute(
            prepared,
            "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:streamGenerateContent",
            context=context,
            key_name="antigravity-oauth",
        )
    ]

    assert chunks
    assert len(wire_capture.outbound_requests) == 1
    assert len(wire_capture.inbound_responses) == 1

    outbound = wire_capture.outbound_requests[0]
    outbound_bytes = outbound["request_payload"]
    outbound_body = json.loads(outbound_bytes.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
    assert outbound["backend"] == "antigravity-oauth"
    assert outbound["model"] == "gemini-2.5-pro"
    assert outbound["key_name"] == "antigravity-oauth"
    assert outbound["capture_metadata"]["url"].endswith(
        "/v1internal:streamGenerateContent?alt=sse"
    )
    assert outbound_body["requestId"] == "req-antigravity"
    assert outbound_body["userAgent"] == "antigravity/1.11.5 windows/amd64"
    assert outbound_body["contents"][0]["parts"][0]["text"] == "hello"

    inbound = wire_capture.inbound_responses[0]
    assert inbound["backend"] == "antigravity-oauth"
    assert inbound["capture_metadata"]["http_status_code"] == 200
    assert inbound["response_content"].startswith(b"HTTP/1.1 200 OK\r\n")
