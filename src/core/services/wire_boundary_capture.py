from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import requests  # type: ignore[import-untyped]

from src.connectors.contracts import ConnectorRequestContext
from src.connectors.contracts.wire_capture_context import (
    WIRE_CAPTURE_ACCOUNT_ID_KEY,
    WIRE_CAPTURE_IS_RETRY_KEY,
    WIRE_CAPTURE_RETRY_ATTEMPT_KEY,
)
from src.core.di.services import get_service_provider
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)
_HTTP_STREAM_CAPTURE_WRAPPED_EXTENSION = "llm_proxy_http_stream_capture_wrapped"


def _is_cbor_wire_capture(wire_capture: IWireCapture | None) -> bool:
    if wire_capture is None:
        return False
    return type(wire_capture).__name__ == "CborWireCaptureService"


def _resolve_wire_capture() -> IWireCapture | None:
    try:
        provider = get_service_provider()
        return provider.get_service(IWireCapture)  # type: ignore[type-abstract]
    except Exception:
        return None


def _build_http_request_bytes(request: httpx.Request) -> bytes:
    split = urlsplit(str(request.url))
    target = split.path or "/"
    if split.query:
        target = f"{target}?{split.query}"
    start_line = f"{request.method} {target} HTTP/1.1\r\n"
    header_lines = [f"{key}: {value}\r\n" for key, value in request.headers.items()]
    body = request.content or b""
    return (
        start_line.encode("utf-8")
        + "".join(header_lines).encode("utf-8", errors="replace")
        + b"\r\n"
        + body
    )


def _detect_http_version(response: httpx.Response) -> str:
    version = response.extensions.get("http_version")
    if isinstance(version, bytes):
        return version.decode("ascii", errors="replace")
    if isinstance(version, str) and version:
        return version
    return "HTTP/1.1"


def _build_http_response_bytes(response: httpx.Response) -> bytes:
    version = _detect_http_version(response)
    reason = response.reason_phrase or ""
    status_line = f"{version} {int(response.status_code)} {reason}\r\n"
    header_lines = [f"{key}: {value}\r\n" for key, value in response.headers.items()]
    try:
        body = response.content or b""
    except Exception:
        body = b""
    return (
        status_line.encode("utf-8")
        + "".join(header_lines).encode("utf-8", errors="replace")
        + b"\r\n"
        + body
    )


def _build_requests_request_bytes(request: requests.PreparedRequest) -> bytes:
    split = urlsplit(str(request.url or ""))
    target = split.path or "/"
    if split.query:
        target = f"{target}?{split.query}"
    start_line = f"{request.method or 'GET'} {target} HTTP/1.1\r\n"
    header_lines = [f"{key}: {value}\r\n" for key, value in request.headers.items()]
    body = request.body or b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return (
        start_line.encode("utf-8")
        + "".join(header_lines).encode("utf-8", errors="replace")
        + b"\r\n"
        + body
    )


def _detect_requests_http_version(response: requests.Response) -> str:
    raw = getattr(response, "raw", None)
    version = getattr(raw, "version", None)
    if isinstance(version, int):
        if version == 10:
            return "HTTP/1.0"
        if version == 11:
            return "HTTP/1.1"
        if version == 20:
            return "HTTP/2"
    return "HTTP/1.1"


def _build_requests_response_bytes(response: requests.Response) -> bytes:
    version = _detect_requests_http_version(response)
    reason = response.reason or ""
    status_line = f"{version} {int(response.status_code)} {reason}\r\n"
    header_lines = [f"{key}: {value}\r\n" for key, value in response.headers.items()]
    body = b""
    raw_content = getattr(response, "_content", None)
    if isinstance(raw_content, bytes):
        body = raw_content
    elif isinstance(raw_content, str):
        body = raw_content.encode("utf-8", errors="replace")
    return (
        status_line.encode("utf-8")
        + "".join(header_lines).encode("utf-8", errors="replace")
        + b"\r\n"
        + body
    )


def _extract_session_id(context: ConnectorRequestContext | None) -> str | None:
    if context is None:
        return None
    session_id = context.session_id
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return None


def _build_request_context(
    context: ConnectorRequestContext | None,
) -> RequestContext | None:
    if context is None:
        return None
    if not context.request_id:
        return None
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
        request_id=context.request_id,
        session_id=context.session_id,
        client_host=context.client_host,
        extensions=dict(context.extensions),
    )


def merge_connector_wire_capture_extensions(
    base: dict[str, Any],
    context: ConnectorRequestContext | None,
) -> dict[str, Any]:
    """Merge ``ConnectorRequestContext.extensions`` wire-capture keys into CBOR metadata.

    Recognized extension keys (see ``wire_capture_context``): account id, retry index,
    retry flag. Other extension keys are ignored here.
    """
    if not context or not context.extensions:
        return base
    ext = context.extensions
    merged = dict(base)
    aid = ext.get(WIRE_CAPTURE_ACCOUNT_ID_KEY)
    if isinstance(aid, str) and aid.strip():
        merged["account_id"] = aid.strip()
    rat = ext.get(WIRE_CAPTURE_RETRY_ATTEMPT_KEY)
    if isinstance(rat, int):
        merged["retry_attempt"] = rat
    elif isinstance(rat, float) and rat.is_integer():
        merged["retry_attempt"] = int(rat)
    ir = ext.get(WIRE_CAPTURE_IS_RETRY_KEY)
    if isinstance(ir, bool):
        merged["is_retry"] = ir
    return merged


def _http_capture_metadata(
    *,
    request: httpx.Request,
    protocol_event: str,
    response_headers: Mapping[str, str] | None = None,
    response_status_code: int | None = None,
    response_reason_phrase: str | None = None,
    response_http_version: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "transport": "http",
        "protocol_event": protocol_event,
        "http_method": request.method,
        "url": str(request.url),
    }
    if response_status_code is not None:
        metadata["status_code"] = int(response_status_code)
        metadata["http_status_code"] = int(response_status_code)
    if response_reason_phrase:
        metadata["http_reason_phrase"] = response_reason_phrase
    if response_http_version:
        metadata["http_version"] = response_http_version
    if response_headers:
        retry_after = response_headers.get("Retry-After") or response_headers.get(
            "retry-after"
        )
        if retry_after is not None:
            with contextlib.suppress(TypeError, ValueError):
                metadata["retry_after_seconds"] = float(retry_after)
    return metadata


def build_http_response_capture_metadata(
    response: httpx.Response,
    *,
    context: ConnectorRequestContext | None = None,
) -> dict[str, Any]:
    base = _http_capture_metadata(
        request=response.request,
        protocol_event="response",
        response_headers=response.headers,
        response_status_code=int(response.status_code),
        response_reason_phrase=response.reason_phrase,
        response_http_version=_detect_http_version(response),
    )
    return merge_connector_wire_capture_extensions(base, context)


def build_requests_response_capture_metadata(
    response: requests.Response,
) -> dict[str, Any]:
    request = response.request
    return _http_capture_metadata(
        request=httpx.Request(
            method=request.method or "GET",
            url=request.url or "",
            headers=request.headers,
        ),
        protocol_event="response",
        response_headers=response.headers,
        response_status_code=int(response.status_code),
        response_reason_phrase=response.reason,
        response_http_version=_detect_requests_http_version(response),
    )


async def _iter_http_response_stream_bytes(stream: Any) -> AsyncIterator[bytes]:
    async for chunk in stream:
        if isinstance(chunk, bytes):
            yield chunk
        elif isinstance(chunk, bytearray):
            yield bytes(chunk)
        elif isinstance(chunk, memoryview):
            yield chunk.tobytes()
        else:
            yield str(chunk).encode("utf-8", errors="replace")


class _CapturedAsyncByteStream(httpx.AsyncByteStream):
    def __init__(
        self, original_stream: Any, wrapped_stream: AsyncIterator[bytes]
    ) -> None:
        self._original_stream = original_stream
        self._wrapped_stream = wrapped_stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._wrapped_stream:
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self._original_stream, "aclose", None)
        if callable(close):
            await cast(Callable[[], Awaitable[None]], close)()


def wrap_http_inbound_response_stream(
    *,
    response: httpx.Response,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
) -> bool:
    if context is None or not context.request_id:
        return False

    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return False

    response_extensions = getattr(response, "extensions", None)
    if isinstance(response_extensions, dict) and response_extensions.get(
        _HTTP_STREAM_CAPTURE_WRAPPED_EXTENSION
    ):
        return True

    response_stream = getattr(response, "stream", None)
    response_request = getattr(response, "request", None)
    if response_stream is None or not isinstance(response_request, httpx.Request):
        return False

    try:
        wrapped_stream = wire_capture.wrap_inbound_stream(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            stream=_iter_http_response_stream_bytes(response_stream),
            capture_metadata=build_http_response_capture_metadata(
                response, context=context
            ),
        )
        response.stream = _CapturedAsyncByteStream(response_stream, wrapped_stream)
        if isinstance(response_extensions, dict):
            response_extensions[_HTTP_STREAM_CAPTURE_WRAPPED_EXTENSION] = True
        return True
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to wrap inbound HTTP response stream for boundary capture",
                exc_info=True,
            )
        return False


async def capture_http_outbound_request(
    *,
    request: httpx.Request,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
) -> None:
    if context is None or not context.request_id:
        return

    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return

    try:
        await wire_capture.capture_outbound_request(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            request_payload=_build_http_request_bytes(request),
            capture_metadata=merge_connector_wire_capture_extensions(
                _http_capture_metadata(
                    request=request,
                    protocol_event="request",
                ),
                context,
            ),
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to capture outbound HTTP boundary request", exc_info=True
            )


async def capture_http_inbound_response(
    *,
    response: httpx.Response,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
) -> None:
    if context is None or not context.request_id:
        return

    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return

    try:
        await wire_capture.capture_inbound_response(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            response_content=_build_http_response_bytes(response),
            capture_metadata=build_http_response_capture_metadata(
                response, context=context
            ),
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to capture inbound HTTP boundary response", exc_info=True
            )


async def capture_requests_outbound_request(
    *,
    request: requests.PreparedRequest,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
) -> None:
    if context is None or not context.request_id:
        return

    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return

    try:
        await wire_capture.capture_outbound_request(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            request_payload=_build_requests_request_bytes(request),
            capture_metadata={
                "transport": "http",
                "protocol_event": "request",
                "http_method": request.method or "GET",
                "url": str(request.url or ""),
            },
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to capture outbound requests boundary request", exc_info=True
            )


async def capture_requests_inbound_response(
    *,
    response: requests.Response,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
) -> None:
    if context is None or not context.request_id:
        return

    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return

    try:
        await wire_capture.capture_inbound_response(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            response_content=_build_requests_response_bytes(response),
            capture_metadata=build_requests_response_capture_metadata(response),
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to capture inbound requests boundary response", exc_info=True
            )


async def capture_websocket_backend_outbound(
    *,
    payload: bytes,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
    message_type: str,
) -> None:
    if context is None or not context.request_id:
        return
    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return
    try:
        await wire_capture.capture_outbound_request(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            request_payload=payload,
            capture_metadata={
                "transport": "websocket",
                "protocol_event": "frame",
                "websocket_message_type": message_type,
            },
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Failed to capture outbound websocket frame", exc_info=True)


async def capture_websocket_backend_inbound(
    *,
    payload: bytes,
    backend: str,
    model: str,
    key_name: str | None,
    context: ConnectorRequestContext | None,
    message_type: str,
) -> None:
    if context is None or not context.request_id:
        return
    wire_capture = _resolve_wire_capture()
    if (
        wire_capture is None
        or not wire_capture.enabled()
        or not _is_cbor_wire_capture(wire_capture)
    ):
        return
    try:
        await wire_capture.capture_inbound_response(
            context=_build_request_context(context),
            session_id=_extract_session_id(context),
            backend=backend,
            model=model,
            key_name=key_name,
            response_content=payload,
            capture_metadata={
                "transport": "websocket",
                "protocol_event": "frame",
                "websocket_message_type": message_type,
            },
        )
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Failed to capture inbound websocket frame", exc_info=True)
