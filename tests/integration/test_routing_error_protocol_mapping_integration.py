from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.common.exceptions import RoutingError
from src.core.transport.fastapi.exception_adapters import register_exception_handlers


def _build_routing_error(*, code: str, retryable: bool, category: str) -> RoutingError:
    return RoutingError(
        message=f"routing failed: {code}",
        details={
            "code": code,
            "retryable": retryable,
            "category": category,
        },
    )


@pytest.mark.parametrize(
    ("routing_code", "retryable", "category", "expected_status", "gemini_status"),
    [
        ("unknown_model", False, "validation", 404, "NOT_FOUND"),
        ("temporarily_unavailable", True, "availability", 503, "UNAVAILABLE"),
    ],
)
def test_routing_error_protocol_shapes_preserve_canonical_semantics(
    routing_code: str,
    retryable: bool,
    category: str,
    expected_status: int,
    gemini_status: str,
) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/v1/chat/completions")
    async def openai_path() -> None:
        raise _build_routing_error(
            code=routing_code,
            retryable=retryable,
            category=category,
        )

    @app.get("/anthropic/v1/messages")
    async def anthropic_path() -> None:
        raise _build_routing_error(
            code=routing_code,
            retryable=retryable,
            category=category,
        )

    @app.get("/v1beta/models/test-model:generateContent")
    async def gemini_path() -> None:
        raise _build_routing_error(
            code=routing_code,
            retryable=retryable,
            category=category,
        )

    with TestClient(app) as client:
        openai_response = client.get("/v1/chat/completions")
        anthropic_response = client.get("/anthropic/v1/messages")
        gemini_response = client.get("/v1beta/models/test-model:generateContent")

    assert openai_response.status_code == expected_status
    assert anthropic_response.status_code == expected_status
    assert gemini_response.status_code == expected_status

    openai_payload = openai_response.json()
    anthropic_payload = anthropic_response.json()
    gemini_payload = gemini_response.json()

    assert openai_payload["error"]["type"] == "routing_error"
    assert anthropic_payload["type"] == "error"
    assert anthropic_payload["error"]["type"] == "routing_error"
    assert gemini_payload["error"]["status"] == gemini_status
    assert gemini_payload["error"]["code"] == expected_status

    assert openai_payload["details"]["code"] == routing_code
    assert anthropic_payload["details"]["code"] == routing_code
    assert gemini_payload["details"]["code"] == routing_code

    assert openai_payload["details"]["retryable"] is retryable
    assert anthropic_payload["details"]["retryable"] is retryable
    assert gemini_payload["details"]["retryable"] is retryable
