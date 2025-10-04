from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.app.middleware.loop_prevention_middleware import LoopPreventionMiddleware
from src.core.security.loop_prevention import (
    LOOP_GUARD_HEADER,
    LOOP_GUARD_VALUE,
    ensure_loop_guard_header,
)


def test_ensure_loop_guard_header_preserves_existing_headers() -> None:
    source = {"Authorization": "Bearer token"}
    guarded = ensure_loop_guard_header(source)
    assert guarded is not source
    assert guarded["Authorization"] == "Bearer token"
    assert guarded[LOOP_GUARD_HEADER] == LOOP_GUARD_VALUE


def test_loop_prevention_middleware_rejects_loop_requests() -> None:
    app = FastAPI()
    app.add_middleware(LoopPreventionMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/ping", headers={LOOP_GUARD_HEADER: LOOP_GUARD_VALUE})
    assert response.status_code == 508
    assert response.json()["detail"] == "Request loop detected"


def test_loop_prevention_middleware_allows_regular_requests() -> None:
    app = FastAPI()
    app.add_middleware(LoopPreventionMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
