"""Plugin-facing HTTP client helpers for capture-aware backend packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.connectors.contracts import ConnectorRequestContext
from src.core.services.wire_boundary_capture import (
    capture_http_inbound_response,
    capture_http_outbound_request,
)

PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION = "llm_proxy_capture_context"
PLUGIN_HTTP_CAPTURED_EXTENSION = "llm_proxy_http_capture_completed"


@dataclass(frozen=True, slots=True)
class PluginHttpCaptureContext:
    """Capture metadata used by plugin-facing HTTP clients."""

    backend: str
    model: str
    key_name: str | None = None
    context: ConnectorRequestContext | None = None


def _resolve_capture_context(
    *,
    request: httpx.Request | None = None,
    response: httpx.Response | None = None,
    default: PluginHttpCaptureContext | None = None,
) -> PluginHttpCaptureContext | None:
    if request is not None:
        request_context = request.extensions.get(PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION)
        if isinstance(request_context, PluginHttpCaptureContext):
            return request_context

    if response is not None:
        response_context = response.extensions.get(
            PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION
        )
        if isinstance(response_context, PluginHttpCaptureContext):
            return response_context

        request_context = response.request.extensions.get(
            PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION
        )
        if isinstance(request_context, PluginHttpCaptureContext):
            return request_context

    return default


class CaptureAwareAsyncClient(httpx.AsyncClient):
    """AsyncClient that captures outbound and non-streaming inbound HTTP traffic."""

    def __init__(
        self,
        *args: Any,
        capture_context: PluginHttpCaptureContext | None = None,
        **kwargs: Any,
    ) -> None:
        self._capture_context = capture_context
        super().__init__(*args, **kwargs)

    async def send(
        self, request: httpx.Request, *args: Any, **kwargs: Any
    ) -> httpx.Response:
        capture_context = _resolve_capture_context(
            request=request,
            default=self._capture_context,
        )
        if capture_context is not None:
            request.extensions.setdefault(
                PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION,
                capture_context,
            )
            await capture_http_outbound_request(
                request=request,
                backend=capture_context.backend,
                model=capture_context.model,
                key_name=capture_context.key_name,
                context=capture_context.context,
            )

        response = await super().send(request, *args, **kwargs)
        if capture_context is not None:
            response.extensions.setdefault(
                PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION,
                capture_context,
            )

        if not bool(kwargs.get("stream", False)) and capture_context is not None:
            await capture_http_inbound_response(
                response=response,
                backend=capture_context.backend,
                model=capture_context.model,
                key_name=capture_context.key_name,
                context=capture_context.context,
            )
            response.extensions[PLUGIN_HTTP_CAPTURED_EXTENSION] = True

        return response


def build_capture_aware_async_client(
    *,
    capture_context: PluginHttpCaptureContext | None = None,
    **client_kwargs: Any,
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` that captures proxy boundary traffic.

    Request-specific capture metadata can be supplied via the public
    ``PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION`` request extension key.
    """

    return CaptureAwareAsyncClient(
        capture_context=capture_context,
        **client_kwargs,
    )


async def capture_http_response(
    response: httpx.Response,
    *,
    capture_context: PluginHttpCaptureContext | None = None,
) -> None:
    """Capture a plugin HTTP response after it has been fully consumed.

    Use this helper for streaming or manually managed responses returned from
    ``httpx.AsyncClient.send(..., stream=True)`` or ``client.stream(...)``.
    """

    if response.extensions.get(PLUGIN_HTTP_CAPTURED_EXTENSION):
        return

    resolved_context = _resolve_capture_context(
        response=response,
        default=capture_context,
    )
    if resolved_context is None:
        return

    await capture_http_inbound_response(
        response=response,
        backend=resolved_context.backend,
        model=resolved_context.model,
        key_name=resolved_context.key_name,
        context=resolved_context.context,
    )
    response.extensions[PLUGIN_HTTP_CAPTURED_EXTENSION] = True


__all__ = [
    "CaptureAwareAsyncClient",
    "PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION",
    "PLUGIN_HTTP_CAPTURED_EXTENSION",
    "PluginHttpCaptureContext",
    "build_capture_aware_async_client",
    "capture_http_response",
]
