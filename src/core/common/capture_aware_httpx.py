"""Connector-safe re-export of capture-aware HTTPX helpers."""

from __future__ import annotations

from src.core.plugin_http_client import (
    build_capture_aware_async_client,
    capture_http_response,
)
from src.core.services.capture_aware_httpx import (
    CaptureAwareAsyncClient,
    HttpxBoundaryCaptureContext,
)

__all__ = [
    "CaptureAwareAsyncClient",
    "HttpxBoundaryCaptureContext",
    "build_capture_aware_async_client",
    "capture_http_response",
]
