"""
Unit tests for OAuthFlowService.

Tests Requirement 1: OAuth2 Authorization Flow.
Note: Browser and callback server tests are skipped - those require integration testing.
"""

import secrets
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.connectors.gemini_oauth_auto.errors import OAuthError
from src.connectors.gemini_oauth_auto.oauth_flow import OAuthFlowService


@pytest.fixture
def mock_storage() -> MagicMock:
    """Fixture providing mock token storage."""
    storage = MagicMock()
    storage.save_account = AsyncMock()
    storage.get_account = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Fixture providing mock httpx AsyncClient."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def oauth_service(mock_storage: MagicMock) -> OAuthFlowService:
    """Fixture providing OAuthFlowService with mocked storage."""
    return OAuthFlowService(storage=mock_storage)


class TestOAuthFlowService:
    """Tests for OAuthFlowService."""

    def test_generate_state_length(self, oauth_service: OAuthFlowService) -> None:
        """Test state parameter is 64 hex characters (32 bytes)."""
        state = oauth_service._generate_state()

        assert len(state) == 64
        # Verify it's valid hex
        int(state, 16)

    def test_generate_state_uniqueness(self, oauth_service: OAuthFlowService) -> None:
        """Test each state is unique."""
        states = [oauth_service._generate_state() for _ in range(100)]
        assert len(set(states)) == 100

    def test_build_auth_url_contains_required_params(
        self, oauth_service: OAuthFlowService
    ) -> None:
        """Test authorization URL contains all required parameters."""
        state = "test_state_12345"
        redirect_uri = "http://localhost:8080/oauth2callback"

        url = oauth_service._build_auth_url(state, redirect_uri)

        assert "accounts.google.com" in url
        assert "client_id=" in url
        assert f"state={state}" in url
        assert "redirect_uri=" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "scope=" in url

    def test_build_auth_url_includes_scopes(
        self, oauth_service: OAuthFlowService
    ) -> None:
        """Test authorization URL includes required scopes."""
        url = oauth_service._build_auth_url("state", "http://localhost:8080/callback")

        # URL-encoded scopes should be present
        assert "cloud-platform" in url
        assert "userinfo.email" in url
        assert "userinfo.profile" in url

    @pytest.mark.asyncio
    async def test_exchange_code_success(
        self,
        oauth_service: OAuthFlowService,
        mock_http_client: MagicMock,
    ) -> None:
        """Test successful code exchange returns tokens."""
        # Mock successful token response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new_access_token",
            "refresh_token": "1//new_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        oauth_service._http_client = mock_http_client

        tokens = await oauth_service._exchange_code(
            code="auth_code_123",
            redirect_uri="http://localhost:8080/callback",
        )

        assert tokens["access_token"] == "ya29.new_access_token"
        assert tokens["refresh_token"] == "1//new_refresh_token"

    @pytest.mark.asyncio
    async def test_exchange_code_failure_raises_error(
        self,
        oauth_service: OAuthFlowService,
        mock_http_client: MagicMock,
    ) -> None:
        """Test code exchange failure raises OAuthError."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Code has expired",
        }
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )
        mock_http_client.post = AsyncMock(return_value=mock_response)

        oauth_service._http_client = mock_http_client

        with pytest.raises(OAuthError) as exc_info:
            await oauth_service._exchange_code("bad_code", "http://localhost/callback")

        assert "invalid_grant" in str(exc_info.value) or "failed" in str(
            exc_info.value
        ).lower()

    @pytest.mark.asyncio
    async def test_fetch_userinfo_returns_email(
        self,
        oauth_service: OAuthFlowService,
        mock_http_client: MagicMock,
    ) -> None:
        """Test userinfo fetch returns email address."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "123456789",
            "email": "testuser@gmail.com",
            "verified_email": True,
            "name": "Test User",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)

        oauth_service._http_client = mock_http_client

        userinfo = await oauth_service._fetch_userinfo("ya29.access_token")

        assert userinfo["email"] == "testuser@gmail.com"

    def test_generate_account_id_from_email(
        self, oauth_service: OAuthFlowService
    ) -> None:
        """Test account ID generation from email."""
        # Test with simple email
        account_id = oauth_service._generate_account_id_from_email("user@gmail.com")
        assert account_id.isalnum() or "-" in account_id or "_" in account_id
        assert len(account_id) <= 64

    def test_generate_account_id_sanitizes_special_chars(
        self, oauth_service: OAuthFlowService
    ) -> None:
        """Test account ID generation sanitizes special characters."""
        account_id = oauth_service._generate_account_id_from_email(
            "test.user+tag@gmail.com"
        )
        # Should not contain dots, plus, or @
        assert "." not in account_id
        assert "+" not in account_id
        assert "@" not in account_id

    def test_validate_state_success(self, oauth_service: OAuthFlowService) -> None:
        """Test state validation succeeds with matching state."""
        expected = "abc123def456"
        received = "abc123def456"

        # Should not raise
        oauth_service._validate_state(expected, received)

    def test_validate_state_failure_raises_error(
        self, oauth_service: OAuthFlowService
    ) -> None:
        """Test state validation failure raises OAuthError."""
        expected = "abc123def456"
        received = "wrong_state_value"

        with pytest.raises(OAuthError) as exc_info:
            oauth_service._validate_state(expected, received)

        assert "state" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_exchange_code_request_format(
        self,
        oauth_service: OAuthFlowService,
        mock_http_client: MagicMock,
    ) -> None:
        """Test code exchange request has correct format."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        oauth_service._http_client = mock_http_client

        await oauth_service._exchange_code("code123", "http://localhost:8080/callback")

        # Verify request format
        call_args = mock_http_client.post.call_args
        assert "oauth2.googleapis.com/token" in call_args[0][0]
        data = call_args[1]["data"]
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "code123"
        assert data["redirect_uri"] == "http://localhost:8080/callback"
        assert "client_id" in data
        assert "client_secret" in data
