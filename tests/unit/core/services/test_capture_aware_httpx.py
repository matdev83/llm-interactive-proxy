from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from src.connectors.contracts import ConnectorRequestContext
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.capture_aware_httpx import (
    CaptureAwareAsyncClient,
    HttpxBoundaryCaptureContext,
)


class CborWireCaptureService(IWireCapture):
    def __init__(self) -> None:
        self.outbound_requests: list[dict[str, Any]] = []
        self.inbound_responses: list[dict[str, Any]] = []
        self.inbound_streams: list[dict[str, Any]] = []

    def enabled(self) -> bool:
        return True

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
        capture_metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
        capture_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.outbound_requests.append(
            {
                "context": context,
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
                "request_payload": request_payload,
                "capture_metadata": capture_metadata,
            }
        )

    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: dict[str, Any] | bytes | None,
        canonical_usage: Any | None = None,
        capture_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.inbound_responses.append(
            {
                "context": context,
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
                "response_content": response_content,
                "capture_metadata": capture_metadata,
            }
        )

    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: AsyncIterator[bytes],
        capture_metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[bytes]:
        stream_call: dict[str, Any] = {
            "context": context,
            "session_id": session_id,
            "backend": backend,
            "model": model,
            "key_name": key_name,
            "capture_metadata": capture_metadata,
            "chunks": [],
        }
        self.inbound_streams.append(stream_call)

        async def _wrapped() -> AsyncIterator[bytes]:
            async for chunk in stream:
                stream_call["chunks"].append(chunk)
                yield chunk

        return _wrapped()

    async def capture_outbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        response_content: dict[str, Any] | bytes | None,
        capture_metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def wrap_outbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        stream: AsyncIterator[bytes],
        capture_metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[bytes]:
        return stream

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: Any | None = None,
        eos_metadata: dict[str, Any] | None = None,
        capture_metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class _AsyncChunksStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _capture_context() -> HttpxBoundaryCaptureContext:
    return HttpxBoundaryCaptureContext(
        backend="openai",
        model="gpt-4o-mini",
        key_name="OPENAI_API_KEY",
        context=ConnectorRequestContext(
            request_id="req-123",
            session_id="sess-123",
            client_host="127.0.0.1",
            extensions={},
        ),
    )


@pytest.mark.asyncio
async def test_capture_aware_httpx_captures_non_streaming_after_final_request_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            request=request,
            headers={"content-type": "application/json"},
            json={"ok": True},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        capture_client = CaptureAwareAsyncClient(client)
        request = client.build_request(
            "POST",
            "https://example.test/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"x-test-header": "final"},
        )

        response = await capture_client.send(
            request,
            stream=False,
            capture=_capture_context(),
        )

    assert response.status_code == 200
    assert len(wire_capture.outbound_requests) == 1
    outbound = wire_capture.outbound_requests[0]
    assert outbound["capture_metadata"]["protocol_event"] == "request"
    assert outbound["capture_metadata"]["http_method"] == "POST"
    assert (
        outbound["capture_metadata"]["url"]
        == "https://example.test/v1/chat/completions"
    )
    outbound_bytes = outbound["request_payload"]
    assert isinstance(outbound_bytes, bytes)
    assert b"x-test-header: final" in outbound_bytes.lower()
    outbound_body = outbound_bytes.split(b"\r\n\r\n", 1)[1]
    assert json.loads(outbound_body.decode("utf-8"))["model"] == "gpt-4o-mini"

    assert len(wire_capture.inbound_responses) == 1
    inbound = wire_capture.inbound_responses[0]
    assert inbound["capture_metadata"]["protocol_event"] == "response"
    assert inbound["capture_metadata"]["http_status_code"] == 200
    inbound_bytes = inbound["response_content"]
    assert isinstance(inbound_bytes, bytes)
    assert b"HTTP/1.1 200" in inbound_bytes
    inbound_body = inbound_bytes.split(b"\r\n\r\n", 1)[1]
    assert json.loads(inbound_body.decode("utf-8")) == {"ok": True}


@pytest.mark.asyncio
async def test_capture_aware_httpx_wraps_streaming_response_without_changing_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_capture = CborWireCaptureService()
    monkeypatch.setattr(
        "src.core.services.wire_boundary_capture._resolve_wire_capture",
        lambda: wire_capture,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            request=request,
            headers={"content-type": "text/event-stream"},
            stream=_AsyncChunksStream([b"data: one\n\n", b"data: two\n\n"]),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        capture_client = CaptureAwareAsyncClient(client)
        request = client.build_request(
            "POST",
            "https://example.test/v1/chat/completions",
            json={"stream": True},
        )

        response = await capture_client.send(
            request,
            stream=True,
            capture=_capture_context(),
        )
        consumed = [chunk async for chunk in response.aiter_bytes()]

    assert consumed == [b"data: one\n\n", b"data: two\n\n"]
    assert len(wire_capture.outbound_requests) == 1
    assert not wire_capture.inbound_responses
    assert len(wire_capture.inbound_streams) == 1
    stream_call = wire_capture.inbound_streams[0]
    assert stream_call["chunks"] == consumed
    assert stream_call["capture_metadata"]["protocol_event"] == "response"
    assert stream_call["capture_metadata"]["http_status_code"] == 200
    assert (
        stream_call["capture_metadata"]["url"]
        == "https://example.test/v1/chat/completions"
    )
