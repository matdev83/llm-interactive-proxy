"""
Unit tests for SSO web interface.

Tests the FastAPI endpoints for SSO authentication flow.
"""

import re

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
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.token_service import TokenService
from src.core.auth.sso.web_interface import create_sso_router


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
    return TokenService(memory_cost=8192, time_cost=1, parallelism=1)


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
