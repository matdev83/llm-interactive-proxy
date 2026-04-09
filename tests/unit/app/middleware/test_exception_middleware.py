from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.middleware.exception_middleware import DomainExceptionMiddleware
from src.core.common.exceptions import DuplicateRequestError, RateLimitExceededError


def test_domain_exception_middleware_sets_retry_after_header(monkeypatch):
    """Test that DomainExceptionMiddleware converts RateLimitExceededError to 429 with Retry-After header."""
    app = FastAPI()
    app.add_middleware(DomainExceptionMiddleware)

    monkeypatch.setattr(
        "src.core.app.middleware.exception_middleware.time.time",
        lambda: 100.0,
    )

    @app.get("/limited")
    async def limited_endpoint() -> None:
        raise RateLimitExceededError("slow down", reset_at=160.2)

    _ = limited_endpoint

    with TestClient(app) as client:
        response = client.get("/limited")

    assert response.status_code == 429
    assert response.headers.get("retry-after") == "61"
    body = response.json()
    assert body["error"]["type"] == "RateLimitExceededError"
    assert body["error"]["message"] == "slow down"


def test_domain_exception_middleware_sets_retry_after_on_duplicate(monkeypatch):
    """DuplicateRequestError should return 429 with Retry-After header."""
    app = FastAPI()
    app.add_middleware(DomainExceptionMiddleware)

    monkeypatch.setattr(
        "src.core.app.middleware.exception_middleware.time.time",
        lambda: 100.0,
    )

    @app.get("/dupe")
    async def duplicate_endpoint() -> None:
        raise DuplicateRequestError(
            "deadbeef",
            "session-1",
            retry_after_seconds=5.2,
        )

    _ = duplicate_endpoint

    with TestClient(app) as client:
        response = client.get("/dupe")

    assert response.status_code == 429
    assert response.headers.get("retry-after") == "6"
    body = response.json()
    assert body["error"]["type"] == "DuplicateRequestError"


async def test_domain_exception_middleware_reraises_transport_error_on_final_body_send():
    """Transport failures on the final body write must not be swallowed."""

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"done",
                "more_body": False,
            }
        )

    middleware = DomainExceptionMiddleware(app)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            raise RuntimeError("client disconnected during final write")

    with pytest.raises(RuntimeError, match="client disconnected during final write"):
        await middleware(scope, receive, send)


async def test_domain_exception_middleware_reraises_transport_error_on_header_send():
    """Header write failures must not trigger a second fallback response write."""

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )

    middleware = DomainExceptionMiddleware(app)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    send_calls: list[str] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        send_calls.append(message["type"])
        if message["type"] == "http.response.start":
            raise RuntimeError("client disconnected during header write")

    with pytest.raises(RuntimeError, match="client disconnected during header write"):
        await middleware(scope, receive, send)

    assert send_calls == ["http.response.start"]
