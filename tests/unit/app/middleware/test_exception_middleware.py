from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.middleware.exception_middleware import DomainExceptionMiddleware
from src.core.common.exceptions import RateLimitExceededError


def test_domain_exception_middleware_sets_retry_after_header(monkeypatch):
    app = FastAPI()
    app.add_middleware(DomainExceptionMiddleware)

    monkeypatch.setattr(
        "src.core.app.middleware.exception_middleware.time.time",
        lambda: 100.0,
    )

    @app.get("/limited")
    async def limited_endpoint() -> None:
        raise RateLimitExceededError("slow down", reset_at=160.2)

    with TestClient(app) as client:
        response = client.get("/limited")

    assert response.status_code == 429
    assert response.headers.get("retry-after") == "61"
    body = response.json()
    assert body["error"]["type"] == "RateLimitExceededError"
    assert body["error"]["message"] == "slow down"
