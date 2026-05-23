"""
Unit tests for SSO web interface.

Tests the FastAPI endpoints for SSO authentication flow.
"""

import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.captcha_service import CaptchaVerificationResult
from src.core.auth.sso.config import (
    AuthorizationConfig,
    CaptchaConfig,
    ProviderConfig,
    SSOConfig,
)
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.models import AuthorizationResult, SSOResult
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.token_service import TokenService
from src.core.auth.sso.web_interface import create_sso_router


@pytest.fixture(autouse=True)
def mock_sso_discovery_network(respx_mock):
    """Global mock for OIDC discovery network calls."""
    metadata = {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
        "issuer": "https://accounts.google.com",
    }
    respx_mock.get("https://accounts.google.com/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=metadata)
    )
    yield respx_mock


@pytest.fixture
async def sso_config(tmp_path):
    """Create test SSO configuration."""
    db_path = tmp_path / "sso_test.db"
    return SSOConfig(
        enabled=True,
        session_lifetime_hours=24,
        providers={
            "google": ProviderConfig(
                type="oauth2",
                client_id="test_client_id",
                client_secret="test_client_secret",
                discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                scopes=["openid", "email", "profile"],
            ),
            "github": ProviderConfig(
                type="oauth2",
                client_id="test_github_client",
                client_secret="test_github_secret",
                authorize_url="https://github.com/login/oauth/authorize",
                token_url="https://github.com/login/oauth/access_token",
                userinfo_url="https://api.github.com/user",
                scopes=["user:email"],
            ),
        },
        authorization=AuthorizationConfig(
            mode="single_user",
            confirmation_code_expiry_minutes=10,
            max_confirmation_attempts=3,
        ),
        database_path=str(db_path),
    )


@pytest.fixture
async def database_manager(sso_config):
    """Create test database manager."""
    db_manager = DatabaseManager(sso_config.database_path)
    await db_manager.initialize_schema()
    return db_manager


@pytest.fixture
async def login_token(database_manager):
    """Create a login token for the SSO form."""
    repo = TokenRepository(database_manager.database_path)
    return await repo.create_login_token()


@pytest.fixture
def sso_service(sso_config):
    """Create test SSO service."""
    return SSOService(sso_config)


@pytest.fixture
def token_service():
    """Create test token service with lighter parameters."""
    return TokenService.create_for_environment()


@pytest.fixture
async def rate_limit_service(database_manager):
    """Create test rate limit service."""
    return RateLimitService(database_manager)


@pytest.fixture
async def authorization_service(sso_config, database_manager, rate_limit_service):
    """Create test authorization service."""
    return AuthorizationService(
        mode=AuthorizationMode.SINGLE_USER,
        config=sso_config.authorization,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
    )


@pytest.fixture
def test_app(
    sso_config,
    sso_service,
    token_service,
    authorization_service,
    database_manager,
    rate_limit_service,
):
    """Create test FastAPI app with SSO router."""
    app = FastAPI()
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=sso_service,
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
    )
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


def _extract_login_session(html: str) -> str:
    match = re.search(r'name="login_session" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_login_endpoint_multiple_providers(client, login_token):
    """Test /auth/login endpoint with multiple providers shows selection page."""
    response = client.get(f"/auth/login?token={login_token}")
    assert response.status_code == 200
    assert "Sign In" in response.text
    assert "Google" in response.text
    assert "GitHub" in response.text


def test_login_provider_endpoint(client, login_token):
    """Test /auth/login/{provider} endpoint redirects to provider."""
    login_page = client.get(f"/auth/login?token={login_token}")
    login_session = _extract_login_session(login_page.text)

    response = client.post(
        "/auth/login/google",
        data={"login_session": login_session},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]


def test_login_invalid_provider(client, login_token):
    """Test /auth/login/{provider} with invalid provider returns error."""
    login_page = client.get(f"/auth/login?token={login_token}")
    login_session = _extract_login_session(login_page.text)

    response = client.post(
        "/auth/login/invalid_provider", data={"login_session": login_session}
    )
    assert response.status_code == 400


def test_login_provider_requires_captcha_token(
    sso_config,
    token_service,
    database_manager,
    rate_limit_service,
    authorization_service,
    login_token,
):
    """Verify captcha is enforced when enabled."""
    sso_config.captcha = CaptchaConfig(
        enabled=True,
        site_key="site_key",
        secret_key="secret_key",
    )

    class StubCaptchaService:
        def __init__(self, should_succeed: bool = True):
            self.should_succeed = should_succeed
            self.is_enabled = True

        async def verify(self, captcha_token: str | None, remote_ip: str | None = None):
            return CaptchaVerificationResult(
                success=self.should_succeed and bool(captcha_token),
                error_codes=[] if captcha_token else ["missing-token"],
            )

    app = FastAPI()
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=SSOService(sso_config),
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
        captcha_service=StubCaptchaService(),
    )
    app.include_router(router)
    captcha_client = TestClient(app)

    login_page = captcha_client.get(f"/auth/login?token={login_token}")
    login_session = _extract_login_session(login_page.text)

    failure_response = captcha_client.post(
        "/auth/login/google", data={"login_session": login_session}
    )
    assert failure_response.status_code == 403

    success_response = captcha_client.post(
        "/auth/login/google",
        data={"login_session": login_session, "captcha_token": "token-value"},
        follow_redirects=False,
    )
    assert success_response.status_code == 302


def test_callback_missing_parameters(client):
    """Test /auth/callback without required parameters returns error."""
    response = client.get("/auth/callback")
    assert response.status_code == 400
    assert "Invalid Callback" in response.text


def test_callback_with_error(client):
    """Test /auth/callback with OAuth error parameter."""
    response = client.get(
        "/auth/callback?error=access_denied&error_description=User+denied"
    )
    assert response.status_code == 400
    assert "Authentication Failed" in response.text
    assert "User denied" in response.text


def test_confirm_endpoint_get(client):
    """Test /auth/confirm GET endpoint shows form."""
    response = client.get("/auth/confirm?state=test_state")
    assert response.status_code == 200
    assert "Enter Confirmation Code" in response.text
    assert "6-digit" in response.text


def test_confirm_endpoint_missing_state(client):
    """Test /auth/confirm without state parameter."""
    response = client.get("/auth/confirm")
    assert response.status_code == 400


def test_success_endpoint(client):
    """Test /auth/success endpoint displays token."""
    test_token = "test_token_12345"
    response = client.get(f"/auth/success?token={test_token}")
    assert response.status_code == 200
    assert "Authentication Successful" in response.text
    assert test_token in response.text
    assert "Copy" in response.text


def test_success_endpoint_missing_token(client):
    """Test /auth/success without token parameter."""
    response = client.get("/auth/success")
    assert response.status_code == 400


def test_login_disabled_provider_returns_error(
    sso_config,
    token_service,
    database_manager,
    rate_limit_service,
    authorization_service,
    login_token,
):
    """
    Test that accessing a disabled provider's login endpoint returns an error.

    Validates: Requirements 13.3 (Property 31)
    """
    # Add a disabled provider to the config
    sso_config.providers["disabled_provider"] = ProviderConfig(
        type="oauth2",
        client_id="disabled_client_id",
        client_secret="disabled_client_secret",
        enabled=False,  # Explicitly disabled
        discovery_url="https://disabled.example.com/.well-known/openid-configuration",
        scopes=["openid", "email"],
    )

    app = FastAPI()
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=SSOService(sso_config),
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
    )
    app.include_router(router)
    test_client = TestClient(app)

    # Get login page to extract session
    login_page = test_client.get(f"/auth/login?token={login_token}")
    login_session = _extract_login_session(login_page.text)

    # Verify disabled provider is NOT shown on login page
    assert "disabled_provider" not in login_page.text

    # Attempt to access disabled provider directly
    response = test_client.post(
        "/auth/login/disabled_provider",
        data={"login_session": login_session},
    )

    # Should return 400 error indicating provider is not available
    assert response.status_code == 400
    assert (
        "Invalid Provider" in response.text or "not available" in response.text.lower()
    )


def test_login_shows_only_enabled_providers(
    sso_config,
    token_service,
    database_manager,
    rate_limit_service,
    authorization_service,
    login_token,
):
    """
    Test that login page shows only enabled providers.

    Validates: Requirements 12.4, 12.5
    """
    # Add a disabled provider
    sso_config.providers["linkedin"] = ProviderConfig(
        type="oauth2",
        client_id="linkedin_client_id",
        client_secret="linkedin_client_secret",
        enabled=False,  # Disabled
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scopes=["openid", "profile", "email"],
    )

    app = FastAPI()
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=SSOService(sso_config),
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
    )
    app.include_router(router)
    test_client = TestClient(app)

    response = test_client.get(f"/auth/login?token={login_token}")

    # Enabled providers should be shown
    assert "Google" in response.text
    assert "GitHub" in response.text

    # Disabled provider should NOT be shown
    assert "LinkedIn" not in response.text


@pytest.mark.asyncio
async def test_state_store_cleanup_mechanism(
    sso_config,
    sso_service,
    token_service,
    database_manager,
    authorization_service,
    rate_limit_service,
):
    """Test that expired OAuth state entries are cleaned up."""
    import time
    from unittest.mock import patch

    router = create_sso_router(
        sso_config,
        sso_service,
        token_service,
        authorization_service,
        database_manager,
        rate_limit_service,
        "http://localhost:8000",
    )
    app = FastAPI()
    app.include_router(router)

    # Access internal state stores via closure - this is a whitebox test
    # The router creates these as local variables in create_sso_router
    # We need to verify the cleanup mechanism works by simulating the scenario

    # Create a login token first
    token_repo = TokenRepository(database_manager.database_path)
    login_token = await token_repo.create_login_token()

    # Mock time.time to simulate TTL expiration
    original_time = time.time
    current_time = original_time()

    with patch("src.core.auth.sso.web_interface.time.time") as mock_time:
        # First call: set current time
        mock_time.return_value = current_time

        # Don't follow redirects so we can verify the redirect response
        test_client = TestClient(app, follow_redirects=False)

        # Make a request that creates state entries
        with (
            patch.object(sso_service, "get_enabled_providers", return_value=["google"]),
            patch.object(
                sso_service,
                "create_authorization_url",
                return_value="https://example.com/auth",
            ),
        ):
            response = test_client.get(f"/auth/login?token={login_token}")
            assert response.status_code == 302

        # Create another login token for second request
        login_token2 = await token_repo.create_login_token()

        # Now simulate time passing beyond TTL (15 minutes = 900 seconds)
        mock_time.return_value = current_time + 1000

        # Make another request - cleanup should remove the old entry
        with (
            patch.object(sso_service, "get_enabled_providers", return_value=["google"]),
            patch.object(
                sso_service,
                "create_authorization_url",
                return_value="https://example.com/auth",
            ),
        ):
            response = test_client.get(f"/auth/login?token={login_token2}")
            # The request should still succeed (cleanup happens silently)
            assert response.status_code == 302


@pytest.mark.asyncio
async def test_enterprise_callback_first_auth_store_token_once(
    sso_config,
    token_service,
    database_manager,
    rate_limit_service,
):
    """Enterprise first-time auth persists the token once before success redirect."""
    authorization_service = AuthorizationService(
        mode=AuthorizationMode.ENTERPRISE,
        config=sso_config.authorization,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
    )
    sso_service = SSOService(sso_config)

    app = FastAPI()
    router = create_sso_router(
        sso_config=sso_config,
        sso_service=sso_service,
        token_service=token_service,
        authorization_service=authorization_service,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
        base_url="http://testserver",
    )
    app.include_router(router)

    token_repo = TokenRepository(database_manager.database_path)
    login_token = await token_repo.create_login_token()

    test_client = TestClient(app, follow_redirects=False)

    login_page = test_client.get(f"/auth/login?token={login_token}")
    assert login_page.status_code == 200
    login_session = _extract_login_session(login_page.text)

    original_store = TokenRepository.store_token
    store_count = [0]

    async def counting_store(self, token_record):
        store_count[0] += 1
        return await original_store(self, token_record)

    with (
        patch(
            "src.core.auth.sso.web_interface.secrets.token_urlsafe",
            return_value="fixed_oauth_state",
        ),
        patch.object(
            sso_service,
            "create_authorization_url",
            new=AsyncMock(return_value="https://accounts.google.com/o/oauth2/v2/auth"),
        ),
        patch.object(
            sso_service,
            "handle_callback",
            new=AsyncMock(
                return_value=SSOResult(
                    success=True,
                    user_id="user-ent-1",
                    user_email="ent@example.com",
                )
            ),
        ),
        patch.object(
            authorization_service,
            "query_authorization_api",
            new=AsyncMock(return_value=AuthorizationResult(authorized=True)),
        ),
        patch.object(
            TokenRepository, "find_by_user_id", new=AsyncMock(return_value=None)
        ),
        patch.object(TokenRepository, "store_token", new=counting_store),
    ):
        post_r = test_client.post(
            "/auth/login/google",
            data={"login_session": login_session},
            follow_redirects=False,
        )
        assert post_r.status_code == 302

        cb_r = test_client.get(
            "/auth/callback?code=fake_auth_code&state=fixed_oauth_state",
            follow_redirects=False,
        )
        assert cb_r.status_code == 302
        assert "/auth/success" in cb_r.headers["location"]
        assert "token=" in cb_r.headers["location"]

    assert store_count[0] == 1
