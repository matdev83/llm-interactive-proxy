"""
Tests for the authentication middleware in the new architecture.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from src.core.security.middleware import APIKeyMiddleware, AuthMiddleware


@pytest.fixture
def mock_request():
    """Create a mock Request object for testing middleware directly."""
    mock = MagicMock(spec=Request)
    mock.url.path = "/test"
    mock.headers = {}
    mock.query_params = {}
    mock.client.host = "127.0.0.1"
    mock.method = "GET"
    return mock


@pytest.fixture
def mock_response():
    """Create a mock Response object."""
    return MagicMock(spec=Response)


@pytest.fixture
def api_key_middleware():
    """Create an APIKeyMiddleware instance with test keys."""
    app = MagicMock()
    test_keys = ["test-key", "another-test-key"]
    return APIKeyMiddleware(app, valid_keys=test_keys)


@pytest.fixture
def auth_token_middleware():
    """Create an AuthMiddleware instance with a test token."""
    app = MagicMock()
    test_token = "test-token"
    return AuthMiddleware(app, valid_token=test_token)


class TestAPIKeyMiddleware:
    """Test the APIKeyMiddleware class."""

    @pytest.mark.asyncio
    async def test_valid_bearer_key(self, api_key_middleware, mock_request):
        """Test that a valid API key in the Authorization header is accepted."""
        # Setup
        mock_request.headers = {"Authorization": "Bearer test-key"}
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await api_key_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_called_once_with(mock_request)
        assert response == "next_response"

    @pytest.mark.asyncio
    async def test_valid_query_key(self, api_key_middleware, mock_request):
        """Test that a valid API key in the query parameters is accepted."""
        # Setup
        mock_request.query_params = {"api_key": "test-key"}
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await api_key_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_called_once_with(mock_request)
        assert response == "next_response"

    @pytest.mark.asyncio
    async def test_invalid_key(self, api_key_middleware, mock_request):
        """Test that an invalid API key is rejected."""
        # Setup
        mock_request.headers = {"Authorization": "Bearer invalid-key"}
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await api_key_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_not_called()
        assert response.status_code == 401
        assert response.body == b'{"detail":"Invalid or missing API key"}'

    @pytest.mark.asyncio
    async def test_missing_key(self, api_key_middleware, mock_request):
        """Test that a missing API key is rejected."""
        # Setup
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await api_key_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_not_called()
        assert response.status_code == 401
        assert response.body == b'{"detail":"Invalid or missing API key"}'

    @pytest.mark.asyncio
    async def test_bypass_path(self, api_key_middleware, mock_request):
        """Test that bypass paths are allowed without authentication."""
        # Setup
        mock_request.url.path = "/docs"
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await api_key_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_called_once_with(mock_request)
        assert response == "next_response"


class TestAuthMiddleware:
    """Test the AuthMiddleware class."""

    @pytest.mark.asyncio
    async def test_valid_token(self, auth_token_middleware, mock_request):
        """Test that a valid auth token is accepted."""
        # Setup
        mock_request.headers = {"X-Auth-Token": "test-token"}
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await auth_token_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_called_once_with(mock_request)
        assert response == "next_response"

    @pytest.mark.asyncio
    async def test_invalid_token(self, auth_token_middleware, mock_request):
        """Test that an invalid auth token is rejected."""
        # Setup
        mock_request.headers = {"X-Auth-Token": "invalid-token"}
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await auth_token_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_not_called()
        assert response.status_code == 401
        assert response.body == b'{"detail":"Invalid or missing auth token"}'

    @pytest.mark.asyncio
    async def test_missing_token(self, auth_token_middleware, mock_request):
        """Test that a missing auth token is rejected."""
        # Setup
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await auth_token_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_not_called()
        assert response.status_code == 401
        assert response.body == b'{"detail":"Invalid or missing auth token"}'

    @pytest.mark.asyncio
    async def test_bypass_path(self, auth_token_middleware, mock_request):
        """Test that bypass paths are allowed without authentication."""
        # Setup
        mock_request.url.path = "/docs"
        call_next = AsyncMock(return_value="next_response")

        # Execute
        response = await auth_token_middleware.dispatch(mock_request, call_next)

        # Verify
        call_next.assert_called_once_with(mock_request)
        assert response == "next_response"


@pytest.fixture
def mock_app():
    """Create a mock FastAPI application."""
    app = FastAPI()

    @app.get("/test")
    def test_endpoint():
        return {"message": "Test endpoint"}

    @app.get("/docs")
    def docs_endpoint():
        return {"message": "Documentation"}

    return app


@pytest.fixture
def client_with_auth(mock_app):
    """Create a test client with authentication enabled."""
    # Add API key middleware
    mock_app.add_middleware(APIKeyMiddleware, valid_keys=["test-key"])

    # Return test client
    return TestClient(mock_app)


@pytest.fixture
def client_with_token_auth(mock_app):
    """Create a test client with token authentication enabled."""
    # Add Auth middleware
    mock_app.add_middleware(AuthMiddleware, valid_token="test-token")

    # Return test client
    return TestClient(mock_app)


@pytest.fixture
def client_without_auth(mock_app):
    """Create a test client without authentication."""
    return TestClient(mock_app)


class TestIntegratedAuthentication:
    """Test authentication integrated with FastAPI."""

    def test_api_key_auth_valid(self, client_with_auth):
        """Test valid API key authentication."""
        response = client_with_auth.get(
            "/test", headers={"Authorization": "Bearer test-key"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "Test endpoint"}

    def test_api_key_auth_invalid(self, client_with_auth):
        """Test invalid API key authentication."""
        response = client_with_auth.get(
            "/test", headers={"Authorization": "Bearer wrong-key"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}

    def test_api_key_auth_missing(self, client_with_auth):
        """Test missing API key."""
        response = client_with_auth.get("/test")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}

    def test_api_key_auth_query_param(self, client_with_auth):
        """Test API key in query parameter."""
        response = client_with_auth.get("/test?api_key=test-key")
        assert response.status_code == 200
        assert response.json() == {"message": "Test endpoint"}

    def test_api_key_auth_bypass_path(self, client_with_auth):
        """Test bypass path with API key authentication."""
        response = client_with_auth.get("/docs")
        assert response.status_code == 200
        # /docs returns HTML content in FastAPI, not JSON
        assert "text/html" in response.headers.get("content-type", "")

    def test_token_auth_valid(self, client_with_token_auth):
        """Test valid token authentication."""
        response = client_with_token_auth.get(
            "/test", headers={"X-Auth-Token": "test-token"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "Test endpoint"}

    def test_token_auth_invalid(self, client_with_token_auth):
        """Test invalid token authentication."""
        response = client_with_token_auth.get(
            "/test", headers={"X-Auth-Token": "wrong-token"}
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing auth token"}

    def test_token_auth_missing(self, client_with_token_auth):
        """Test missing token."""
        response = client_with_token_auth.get("/test")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing auth token"}

    def test_token_auth_bypass_path(self, client_with_token_auth):
        """Test bypass path with token authentication."""
        response = client_with_token_auth.get("/docs")
        assert response.status_code == 200
        # /docs returns HTML content in FastAPI, not JSON
        assert "text/html" in response.headers.get("content-type", "")

    def test_no_auth(self, client_without_auth):
        """Test endpoint without authentication."""
        response = client_without_auth.get("/test")
        assert response.status_code == 200
        assert response.json() == {"message": "Test endpoint"}


class TestAppIntegration:
    """Test full application integration with authentication."""

    @patch("src.core.security.middleware.APIKeyMiddleware")
    def test_app_with_auth_disabled(self, mock_middleware):
        """Test application with authentication disabled."""
        # Setup environment
        with patch.dict(os.environ, {"DISABLE_AUTH": "true"}):
            # Import locally to ensure environment variables are read
            from src.core.app.middleware_config import configure_middleware

            # Create mock app
            app = MagicMock(spec=FastAPI)

            # Configure middleware
            configure_middleware(app, {"disable_auth": True})

            # Verify
            mock_middleware.assert_not_called()

    @patch("src.core.security.middleware.APIKeyMiddleware")
    def test_app_with_auth_enabled(self, mock_middleware):
        """Test application with authentication enabled."""
        # Setup environment
        with patch.dict(os.environ, {"DISABLE_AUTH": "false"}):
            # Import locally to ensure environment variables are read
            from src.core.app.middleware_config import configure_middleware

            # Create mock app
            app = MagicMock(spec=FastAPI)

            # Configure middleware
            configure_middleware(app, {"disable_auth": False, "api_keys": ["test-key"]})

            # Verify
            app.add_middleware.assert_any_call(
                APIKeyMiddleware, valid_keys=["test-key"]
            )

    @patch("src.core.security.middleware.AuthMiddleware")
    def test_app_with_auth_token(self, mock_middleware):
        """Test application with auth token enabled."""
        # Import locally to ensure environment variables are read
        from src.core.app.middleware_config import configure_middleware

        # Create mock app
        app = MagicMock(spec=FastAPI)

        # Configure middleware
        configure_middleware(app, {"auth_token": "test-token"})

        # Verify
        app.add_middleware.assert_any_call(
            AuthMiddleware, valid_token="test-token", bypass_paths=["/docs"]
        )
