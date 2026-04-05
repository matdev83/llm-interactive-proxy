from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.connectors.contracts import ConnectorRequestContext
from src.core.services.wire_boundary_capture import (
    capture_http_inbound_response,
    capture_http_outbound_request,
    wrap_http_inbound_response_stream,
)


@dataclass(frozen=True, slots=True)
class HttpxBoundaryCaptureContext:
    backend: str
    model: str
    key_name: str | None
    context: ConnectorRequestContext | None


class CaptureAwareAsyncClient:
    """Shared HTTPX wrapper for backend boundary capture.

    The wrapper captures outbound requests after the final `httpx.Request`
    has been built and captures inbound responses before connector-level
    translation. Streaming responses keep normal HTTPX semantics by wrapping
    the response byte stream instead of eagerly draining it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool,
        capture: HttpxBoundaryCaptureContext,
    ) -> httpx.Response:
        await capture_http_outbound_request(
            request=request,
            backend=capture.backend,
            model=capture.model,
            key_name=capture.key_name,
            context=capture.context,
        )

        response = await self._client.send(request, stream=stream)
        if stream:
            wrap_http_inbound_response_stream(
                response=response,
                backend=capture.backend,
                model=capture.model,
                key_name=capture.key_name,
                context=capture.context,
            )
            return response

        await response.aread()
        await capture_http_inbound_response(
            response=response,
            backend=capture.backend,
            model=capture.model,
            key_name=capture.key_name,
            context=capture.context,
        )
        return response
