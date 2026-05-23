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


@pytest.mark.asyncio
async def test_sso_middleware_adapter_skips_auth_endpoints(mock_sso_middleware):
    """Test that SSO middleware skips /auth/ endpoints."""
    app = AsyncMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/login",
        "headers": [],
    }
    receive = AsyncMock(
        return_value={"type": "http.request", "body": b"", "more_body": False}
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    # Should call app without checking SSO
    app.assert_called_once()
    mock_sso_middleware.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_skips_health_endpoints(mock_sso_middleware):
    """Test that SSO middleware skips /health endpoint."""
    app = AsyncMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
    }
    receive = AsyncMock(
        return_value={"type": "http.request", "body": b"", "more_body": False}
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    # Should call app without checking SSO
    app.assert_called_once()
    mock_sso_middleware.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_returns_sandbox_when_unauthenticated(
    mock_sso_middleware,
):
    """Test that adapter returns sandbox response when user is unauthenticated."""
    app = AsyncMock()
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

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"authorization", b"Bearer test-token")],
    }
    receive = AsyncMock(
        return_value={
            "type": "http.request",
            "body": b'{"messages": []}',
            "more_body": False,
        }
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    # Should send sandbox response
    assert send.call_count >= 2  # response.start and response.body
    # Should not call app
    app.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_continues_when_authenticated(mock_sso_middleware):
    """Test that adapter continues to next middleware when user is authenticated."""
    app = AsyncMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    # Mock SSO middleware to return None (authenticated)
    mock_sso_middleware.return_value = None

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"authorization", b"Bearer test-token")],
    }
    receive = AsyncMock(
        return_value={
            "type": "http.request",
            "body": b'{"messages": []}',
            "more_body": False,
        }
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    # Should call app
    app.assert_called_once()
    # Should call SSO middleware
    mock_sso_middleware.assert_called_once()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_handles_errors_gracefully(mock_sso_middleware):
    """Test that adapter handles SSO middleware errors gracefully."""
    app = AsyncMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    # Mock SSO middleware to raise an exception
    mock_sso_middleware.side_effect = Exception("SSO error")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"authorization", b"Bearer test-token")],
    }
    receive = AsyncMock(
        return_value={
            "type": "http.request",
            "body": b'{"messages": []}',
            "more_body": False,
        }
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    # Should send sandbox response on error
    assert send.call_count >= 2  # response.start and response.body
    # Should not call app
    app.assert_not_called()


@pytest.mark.asyncio
async def test_sso_middleware_adapter_propagates_request_state_to_scope(
    mock_sso_middleware,
):
    """Test that middleware request_state is injected into ASGI scope state."""
    app = AsyncMock()
    adapter = SSOMiddlewareAdapter(app, mock_sso_middleware)

    async def _authenticated_with_identity(request_dict):
        request_dict["request_state"] = {
            "auth_scope_id": "token-id-1",
            "authenticated_user_id": "user-1",
        }
        return None

    mock_sso_middleware.side_effect = _authenticated_with_identity

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [(b"authorization", b"Bearer test-token")],
        "state": {"request_state": {"existing_key": "existing-value"}},
    }
    receive = AsyncMock(
        return_value={
            "type": "http.request",
            "body": b'{"messages": []}',
            "more_body": False,
        }
    )
    send = AsyncMock()

    await adapter(scope, receive, send)

    app.assert_called_once()
    app_scope = app.call_args.args[0]
    assert app_scope["state"]["request_state"] == {
        "existing_key": "existing-value",
        "auth_scope_id": "token-id-1",
        "authenticated_user_id": "user-1",
    }
