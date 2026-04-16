from __future__ import annotations

import httpx
from src.connectors.contracts import ConnectorRequestContext
from src.connectors.contracts.wire_capture_context import (
    WIRE_CAPTURE_ACCOUNT_ID_KEY,
    WIRE_CAPTURE_IS_RETRY_KEY,
    WIRE_CAPTURE_RETRY_ATTEMPT_KEY,
)
from src.core.services.wire_boundary_capture import (
    build_http_response_capture_metadata,
    merge_connector_wire_capture_extensions,
)


def test_merge_connector_wire_capture_extensions() -> None:
    base = {"transport": "http", "protocol_event": "request"}
    ctx = ConnectorRequestContext(
        request_id="r1",
        session_id="s1",
        client_host=None,
        extensions={
            WIRE_CAPTURE_ACCOUNT_ID_KEY: "acc-9",
            WIRE_CAPTURE_RETRY_ATTEMPT_KEY: 2,
            WIRE_CAPTURE_IS_RETRY_KEY: True,
        },
    )
    merged = merge_connector_wire_capture_extensions(base, ctx)
    assert merged["transport"] == "http"
    assert merged["account_id"] == "acc-9"
    assert merged["retry_attempt"] == 2
    assert merged["is_retry"] is True


def test_build_http_response_capture_metadata_merges_context() -> None:
    req = httpx.Request("POST", "https://example.com/x")
    resp = httpx.Response(429, request=req, headers={"Retry-After": "12"})
    ctx = ConnectorRequestContext(
        request_id="r1",
        session_id="s1",
        client_host=None,
        extensions={
            WIRE_CAPTURE_ACCOUNT_ID_KEY: "managed-uuid",
            WIRE_CAPTURE_RETRY_ATTEMPT_KEY: 0,
            WIRE_CAPTURE_IS_RETRY_KEY: False,
        },
    )
    meta = build_http_response_capture_metadata(resp, context=ctx)
    assert meta["http_status_code"] == 429
    assert meta["account_id"] == "managed-uuid"
    assert meta["retry_attempt"] == 0
    assert meta["is_retry"] is False
    assert meta["retry_after_seconds"] == 12.0
