from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.common.exceptions import RoutingError
from src.core.transport.fastapi.exception_adapters import register_exception_handlers


@pytest.mark.parametrize(
    ("routing_code", "expected_status"),
    [
        ("unknown_model", 404),
        ("temporarily_unavailable", 503),
    ],
)
def test_routing_error_http_mapping_preserves_code_and_status(
    routing_code: str, expected_status: int
) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/routing-error")
    async def routing_error() -> dict[str, str]:
        raise RoutingError(
            message=f"routing failed: {routing_code}",
            details={
                "code": routing_code,
                "retryable": routing_code == "temporarily_unavailable",
                "category": "availability",
            },
        )

    with TestClient(app) as client:
        response = client.get("/routing-error")
        assert response.status_code == expected_status
        payload = response.json()
        assert payload["details"]["code"] == routing_code
