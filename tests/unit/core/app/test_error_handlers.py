from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from src.core.app.error_handlers import (
    configure_exception_handlers,
    general_exception_handler,
    http_exception_handler,
    proxy_exception_handler,
    validation_exception_handler,
)
from src.core.common.exceptions import LLMProxyError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response


def make_request(path: str) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope, receive=receive)


def parse_json_response(response: Response) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def call_handler(func, *args, **kwargs) -> Response:
    return asyncio.run(func(*args, **kwargs))


def test_validation_exception_handler_formats_errors() -> None:
    request = make_request("/v1/test")
    exc = RequestValidationError(
        [
            {
                "loc": ("body", "field"),
                "msg": "field required",
                "type": "value_error.missing",
            }
        ]
    )

    response = call_handler(validation_exception_handler, request, exc)

    assert response.status_code == 400
    payload = parse_json_response(response)
    assert payload["detail"]["error"]["details"]["errors"] == [
        {
            "loc": ["body", "field"],
            "msg": "field required",
            "type": "value_error.missing",
        }
    ]


def test_http_exception_handler_standard_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: 1700000000)
    request = make_request("/v1/models")
    exc = HTTPException(status_code=404, detail="Missing")

    response = call_handler(http_exception_handler, request, exc)

    assert response.status_code == 404
    payload = parse_json_response(response)
    assert payload == {
        "detail": {
            "error": {
                "message": "Missing",
                "type": "HttpError",
                "status_code": 404,
            }
        }
    }


def test_http_exception_handler_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: 1700000000)
    request = make_request("/v1/chat/completions")
    exc = HTTPException(status_code=429, detail="Try again later")

    response = call_handler(http_exception_handler, request, exc)

    assert response.status_code == 429
    payload = parse_json_response(response)
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["finish_reason"] == "error"
    assert payload["error"] == {
        "message": "Try again later",
        "type": "HttpError",
        "status_code": 429,
    }


def test_proxy_exception_handler_chat_completion_with_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: 1700000000)
    request = make_request("/v1/chat/completions")
    exc = LLMProxyError(
        "backend rejected",
        details={"backend": "alpha"},
        status_code=422,
    )

    response = call_handler(proxy_exception_handler, request, exc)

    assert response.status_code == 422
    payload = parse_json_response(response)
    assert payload["error"]["status_code"] == 422
    assert payload["error"]["details"] == {"backend": "alpha"}


def test_proxy_exception_handler_standard_all_backends_failed() -> None:
    request = make_request("/v1/completions")
    exc = LLMProxyError("all backends failed", status_code=418)

    response = call_handler(proxy_exception_handler, request, exc)

    assert response.status_code == 500
    payload = parse_json_response(response)
    assert payload["detail"]["error"]["message"] == "all backends failed"
    assert payload["detail"]["error"]["status_code"] == 500


def test_proxy_exception_handler_non_proxy_exception() -> None:
    request = make_request("/v1/completions")
    exc = RuntimeError("unexpected failure")

    response = call_handler(proxy_exception_handler, request, exc)  # type: ignore[arg-type]

    assert response.status_code == 500
    payload = parse_json_response(response)
    assert payload == {
        "detail": {
            "error": {
                "message": "unexpected failure",
                "type": "RuntimeError",
                "status_code": 500,
            }
        }
    }


def test_general_exception_handler_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: 1700000000)
    request = make_request("/v1/chat/completions")

    response = call_handler(general_exception_handler, request, RuntimeError("boom"))

    assert response.status_code == 500
    payload = parse_json_response(response)
    assert payload["object"] == "chat.completion"
    assert payload["error"] == {
        "message": "Internal Server Error",
        "type": "InternalError",
        "status_code": 500,
    }


def test_general_exception_handler_standard_request() -> None:
    request = make_request("/v1/embeddings")

    response = call_handler(general_exception_handler, request, RuntimeError("boom"))

    assert response.status_code == 500
    payload = parse_json_response(response)
    assert payload == {
        "detail": {
            "error": {
                "message": "Internal Server Error",
                "type": "InternalError",
                "status_code": 500,
            }
        }
    }


def test_general_exception_handler_logs_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    request = make_request("/v1/embeddings")

    captured: dict[str, Any] = {}

    def fake_exception(
        message: str,
        *,
        exc_info: tuple[type[Exception], Exception, Any] | None = None,
        **_: Any,
    ) -> None:
        captured["message"] = message
        captured["exc_info"] = exc_info

    monkeypatch.setattr(
        "src.core.app.error_handlers.logger.exception",
        fake_exception,
    )

    caught: RuntimeError | None = None
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        caught = exc
        response = call_handler(general_exception_handler, request, exc)

    assert response.status_code == 500
    assert captured["message"] == "Unhandled exception"
    exc_info = captured["exc_info"]
    assert exc_info is not None
    assert exc_info[0] is RuntimeError
    assert caught is not None
    assert exc_info[1] is caught
    assert exc_info[2] is caught.__traceback__


def test_configure_exception_handlers_registers_handlers() -> None:
    app = FastAPI()

    configure_exception_handlers(app)

    assert RequestValidationError in app.exception_handlers
    assert HTTPException in app.exception_handlers
    assert LLMProxyError in app.exception_handlers
    assert Exception in app.exception_handlers
