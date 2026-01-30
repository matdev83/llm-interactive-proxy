from __future__ import annotations

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
