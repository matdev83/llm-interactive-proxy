"""Tests for the stable plugin API surface."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from src.core.plugin_api import (
    BACKEND_PLUGIN_ENTRY_POINT_GROUP,
    PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION,
    PLUGIN_HTTP_CAPTURED_EXTENSION,
    BackendPluginDefinition,
    PluginCompatibility,
    PluginHttpCaptureContext,
    build_capture_aware_async_client,
    capture_http_response,
)


def _mock_response_handler(
    status_code: int = 200, body: bytes = b"ok"
) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body, request=request)

    return _handler


def test_plugin_api_preserves_existing_exports() -> None:
    """The public plugin API should keep legacy exports intact."""

    assert BACKEND_PLUGIN_ENTRY_POINT_GROUP == "llm_proxy_backends"
    assert BackendPluginDefinition.__name__ == "BackendPluginDefinition"
    assert PluginCompatibility.__name__ == "PluginCompatibility"


@pytest.mark.asyncio
async def test_capture_aware_client_uses_request_extensions_and_captures_response() -> (
    None
):
    default_context = PluginHttpCaptureContext(
        backend="default-backend",
        model="default-model",
        key_name="default-key",
    )
    override_context = PluginHttpCaptureContext(
        backend="override-backend",
        model="override-model",
        key_name="override-key",
    )
    outbound_capture = AsyncMock()
    inbound_capture = AsyncMock()
    transport = httpx.MockTransport(_mock_response_handler())

    with (
        patch(
            "src.core.plugin_http_client.capture_http_outbound_request",
            outbound_capture,
        ),
        patch(
            "src.core.plugin_http_client.capture_http_inbound_response",
            inbound_capture,
        ),
    ):
        async with build_capture_aware_async_client(
            capture_context=default_context,
            transport=transport,
            base_url="https://plugin.example.test",
        ) as client:
            request = client.build_request(
                "GET",
                "/v1/models",
            )
            request.extensions[PLUGIN_HTTP_CAPTURE_CONTEXT_EXTENSION] = override_context
            response = await client.send(request)

    assert response.text == "ok"
    assert response.extensions[PLUGIN_HTTP_CAPTURED_EXTENSION] is True

    outbound_call = outbound_capture.await_args
    inbound_call = inbound_capture.await_args
    assert outbound_call is not None
    assert inbound_call is not None
    outbound_kwargs = outbound_call.kwargs
    inbound_kwargs = inbound_call.kwargs

    assert outbound_kwargs["backend"] == "override-backend"
    assert outbound_kwargs["model"] == "override-model"
    assert outbound_kwargs["key_name"] == "override-key"
    assert outbound_kwargs["context"] is None
    assert inbound_kwargs["backend"] == "override-backend"
    assert inbound_kwargs["model"] == "override-model"
    assert inbound_kwargs["key_name"] == "override-key"


@pytest.mark.asyncio
async def test_capture_http_response_supports_streaming_responses() -> None:
    capture_context = PluginHttpCaptureContext(
        backend="stream-backend",
        model="stream-model",
        key_name="stream-key",
    )
    outbound_capture = AsyncMock()
    inbound_capture = AsyncMock()
    transport = httpx.MockTransport(_mock_response_handler(body=b"stream-body"))

    with (
        patch(
            "src.core.plugin_http_client.capture_http_outbound_request",
            outbound_capture,
        ),
        patch(
            "src.core.plugin_http_client.capture_http_inbound_response",
            inbound_capture,
        ),
    ):
        async with build_capture_aware_async_client(
            capture_context=capture_context,
            transport=transport,
            base_url="https://plugin.example.test",
        ) as client:
            request = client.build_request("GET", "/v1/stream")
            response = await client.send(request, stream=True)
            await response.aread()
            await capture_http_response(response)
            await capture_http_response(response)

    assert outbound_capture.await_count == 1
    assert inbound_capture.await_count == 1
    outbound_call = outbound_capture.await_args
    inbound_call = inbound_capture.await_args
    assert outbound_call is not None
    assert inbound_call is not None
    outbound_kwargs = outbound_call.kwargs
    inbound_kwargs = inbound_call.kwargs
    assert outbound_kwargs["backend"] == "stream-backend"
    assert inbound_kwargs["backend"] == "stream-backend"
    assert response.extensions[PLUGIN_HTTP_CAPTURED_EXTENSION] is True
