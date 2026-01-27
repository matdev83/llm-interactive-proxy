"""Tests for RequestIDMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.app.middleware.request_id_middleware import RequestIDMiddleware


@pytest.mark.asyncio
async def test_request_id_middleware_extracts_from_header() -> None:
    """Test that RequestIDMiddleware extracts request ID from X-Request-ID header."""
    # Mock ASGI app
    app = AsyncMock()
    middleware = RequestIDMiddleware(app)

    # Create ASGI scope with X-Request-ID header
    scope = {
        "type": "http",
        "headers": [(b"x-request-id", b"header-id-123")],
    }
    receive = AsyncMock()

    # Track headers added to response
    captured_headers = []

    async def send(message):
        if message["type"] == "http.response.start":
            captured_headers.extend(message.get("headers", []))

    await middleware(scope, receive, send)

    # Verify request ID was stored in scope state
    assert scope["state"]["request_id"] == "header-id-123"

    # Verify app was called
    app.assert_called_once()


@pytest.mark.asyncio
async def test_request_id_middleware_generates_id() -> None:
    """Test that RequestIDMiddleware generates a request ID when missing."""
    # Mock ASGI app
    app = AsyncMock()
    middleware = RequestIDMiddleware(app)

    # Create ASGI scope without request ID header
    scope = {
        "type": "http",
        "headers": [],
    }
    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    # Verify request ID was generated and stored
    assert "state" in scope
    assert "request_id" in scope["state"]
    request_id = scope["state"]["request_id"]
    assert request_id is not None
    assert request_id.startswith("req-")

    # Verify app was called
    app.assert_called_once()
