"""Tests for RequestIDMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request, Response
from src.core.app.middleware.request_id_middleware import RequestIDMiddleware


@pytest.mark.asyncio
async def test_request_id_middleware_extracts_from_header() -> None:
    """Test that RequestIDMiddleware extracts request ID from X-Request-ID header."""
    app = MagicMock()
    middleware = RequestIDMiddleware(app)
    
    request = MagicMock(spec=Request)
    request.headers = {"x-request-id": "header-id-123"}
    request.state = MagicMock()
    
    response = MagicMock(spec=Response)
    response.headers = {}
    
    call_next = AsyncMock(return_value=response)
    
    result = await middleware.dispatch(request, call_next)
    
    assert request.state.request_id == "header-id-123"
    assert result.headers["X-Request-ID"] == "header-id-123"


@pytest.mark.asyncio
async def test_request_id_middleware_generates_id() -> None:
    """Test that RequestIDMiddleware generates a request ID when missing."""
    app = MagicMock()
    middleware = RequestIDMiddleware(app)
    
    request = MagicMock(spec=Request)
    request.headers = {}
    request.state = MagicMock()
    
    response = MagicMock(spec=Response)
    response.headers = {}
    
    call_next = AsyncMock(return_value=response)
    
    result = await middleware.dispatch(request, call_next)
    
    assert request.state.request_id is not None
    assert request.state.request_id.startswith("req-")
    assert result.headers["X-Request-ID"] == request.state.request_id
