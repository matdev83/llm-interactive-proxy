"""
Unit tests for SSO middleware integration.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.middleware.sso_middleware_adapter import SSOMiddlewareAdapter


@pytest.fixture
def mock_sso_middleware():
    """Create a mock SSO middleware."""
    middleware = AsyncMock()
    middleware.sandbox_handler = MagicMock()
    middleware.sandbox_handler.generate_login_banner = AsyncMock(
        return_value={
            "id": "sandbox-1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Please authenticate at http://localhost:8000/auth/login",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )
    return middleware


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.method = "POST"
    request.headers = {"authorization": "Bearer test-token"}
    request.body = AsyncMock(return_value=b'{"messages": []}')
    return request


@pytest.mark.asyncio
async def test_sso_middleware_adapter_skips_auth_endpoints(mock_sso_middleware):
    """Test that SSO middleware skips /auth/ endpoints."""
    app = MagicMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    request = MagicMock()
    request.url.path = "/auth/login"

    call_next = AsyncMock(return_value=MagicMock(status_code=200))

    await adapter.dispatch(request, call_next)

    # Should call next middleware without checking SSO
    call_next.assert_called_once()
    mock_sso_middleware.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_skips_health_endpoints(mock_sso_middleware):
    """Test that SSO middleware skips /health endpoint."""
    app = MagicMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    request = MagicMock()
    request.url.path = "/health"

    call_next = AsyncMock(return_value=MagicMock(status_code=200))

    await adapter.dispatch(request, call_next)

    # Should call next middleware without checking SSO
    call_next.assert_called_once()
    mock_sso_middleware.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_returns_sandbox_when_unauthenticated(
    mock_sso_middleware, mock_request
):
    """Test that adapter returns sandbox response when user is unauthenticated."""
    app = MagicMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    # Mock SSO middleware to return sandbox response
    sandbox_response = {
        "id": "sandbox-1",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Please authenticate",
                },
                "finish_reason": "stop",
            }
        ],
    }
    mock_sso_middleware.return_value = sandbox_response

    call_next = AsyncMock()

    response = await adapter.dispatch(mock_request, call_next)

    # Should return sandbox response
    assert response.status_code == 200
    # Should not call next middleware
    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_continues_when_authenticated(
    mock_sso_middleware, mock_request
):
    """Test that adapter continues to next middleware when user is authenticated."""
    app = MagicMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    # Mock SSO middleware to return None (authenticated)
    mock_sso_middleware.return_value = None

    call_next = AsyncMock(return_value=MagicMock(status_code=200))

    await adapter.dispatch(mock_request, call_next)

    # Should call next middleware
    call_next.assert_called_once()
    # Should call SSO middleware
    mock_sso_middleware.assert_called_once()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_handles_errors_gracefully(
    mock_sso_middleware, mock_request
):
    """Test that adapter handles SSO middleware errors gracefully."""
    app = MagicMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    # Mock SSO middleware to raise an exception
    mock_sso_middleware.side_effect = Exception("SSO error")

    call_next = AsyncMock()

    response = await adapter.dispatch(mock_request, call_next)

    # Should return sandbox response on error
    assert response.status_code == 200
    # Should not call next middleware
    call_next.assert_not_called()
