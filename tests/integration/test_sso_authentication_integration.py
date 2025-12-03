"""
Integration tests for SSO authentication feature.

Tests the complete authentication flows including:
- Full authentication flow (SSO -> Authorization -> Token generation)
- Re-authentication flow (Expired session -> SSO -> Status update)
- Sandbox isolation (Sandbox sessions cannot continue after auth)
"""

import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.middleware import AuthMiddleware
from src.core.auth.sso.models import SSOResult, TokenRecord
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.token_service import TokenService


@pytest.fixture
async def sso_config(tmp_path):
    """Create test SSO configuration."""
    # Use a temporary file instead of :memory: so all fixtures share the same database
    db_path = str(tmp_path / "test_sso.db")
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
        },
        authorization=AuthorizationConfig(
            mode="single_user",
            confirmation_code_expiry_minutes=10,
            max_confirmation_attempts=3,
        ),
        database_path=db_path,
    )


@pytest.fixture
async def database_manager(sso_config):
    """Create test database manager."""
    db_manager = DatabaseManager(sso_config.database_path)
    await db_manager.initialize_schema()
    return db_manager


@pytest.fixture
async def token_repository(database_manager, sso_config):
    """Create test token repository."""
    from src.core.auth.sso.database import TokenRepository

    # Database is already initialized by database_manager fixture
    return TokenRepository(sso_config.database_path)


@pytest.fixture
def token_service():
    """Create test token service with lighter parameters for faster tests."""
    return TokenService(memory_cost=8192, time_cost=1, parallelism=1)


@pytest.fixture
async def rate_limit_service(database_manager):
    """Create test rate limit service."""
    return RateLimitService(database_manager)


@pytest.fixture
async def authorization_service_single_user(
    sso_config, database_manager, rate_limit_service
):
    """Create test authorization service in single-user mode."""
    return AuthorizationService(
        mode=AuthorizationMode.SINGLE_USER,
        config=sso_config.authorization,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
    )


@pytest.fixture
async def authorization_service_enterprise(
    sso_config, database_manager, rate_limit_service
):
    """Create test authorization service in enterprise mode."""
    enterprise_config = AuthorizationConfig(
        mode="enterprise",
        api_url="http://localhost:9999/authorize",
        api_timeout=5,
    )
    return AuthorizationService(
        mode=AuthorizationMode.ENTERPRISE,
        config=enterprise_config,
        database_manager=database_manager,
        rate_limit_service=rate_limit_service,
    )


@pytest.fixture
def sso_service(sso_config):
    """Create test SSO service."""
    return SSOService(sso_config)


@pytest.fixture
def sandbox_handler():
    """Create test sandbox handler."""
    return SandboxHandler(auth_url="http://localhost:8080/auth/login")


@pytest.fixture
async def auth_middleware(token_repository, token_service, sandbox_handler):
    """Create test auth middleware."""
    return AuthMiddleware(
        token_service=token_service,
        token_repository=token_repository,
        sandbox_handler=sandbox_handler,
    )


class TestFullAuthenticationFlow:
    """
    Test 20.1: Full authentication flow
    Tests SSO -> Authorization -> Token generation
    Requirements: 1.1, 3.1, 6.5, 7.3
    """

    @pytest.mark.asyncio
    async def test_single_user_full_flow(
        self,
        sso_service,
        authorization_service_single_user,
        token_service,
        token_repository,
    ):
        """Test complete authentication flow in single-user mode."""
        # Step 1: Simulate SSO authentication
        sso_result = SSOResult(
            success=True,
            user_id="test_user_123",
            user_email="test@example.com",
            provider="google",
            error=None,
        )

        # Step 2: Simulate authorization (in real flow, user enters confirmation code)
        # For integration test, we skip the confirmation code flow and go straight to token generation
        # The confirmation code flow is tested in unit tests

        # Step 3: Generate token
        plaintext_token, token_hash = token_service.generate_token()

        # Step 4: Store token in database
        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id=sso_result.user_id,
            user_email=sso_result.user_email,
            provider=sso_result.provider,
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=datetime.now(timezone.utc),
            auth_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        await token_repository.store_token(token_record)

        # Step 5: Verify token can be retrieved and validated
        retrieved_record = await token_repository.find_by_hash(token_hash)
        assert retrieved_record is not None
        assert retrieved_record.user_email == "test@example.com"
        assert retrieved_record.is_authenticated is True
        assert retrieved_record.is_active is True

        # Step 6: Verify token service can validate the token
        is_valid = token_service.verify_token(plaintext_token, token_hash)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_enterprise_full_flow(
        self,
        sso_service,
        authorization_service_enterprise,
        token_service,
        token_repository,
    ):
        """Test complete authentication flow in enterprise mode."""
        # Step 1: Simulate SSO authentication
        sso_result = SSOResult(
            success=True,
            user_id="enterprise_user_456",
            user_email="enterprise@company.com",
            provider="google",
            error=None,
        )

        # Step 2: Mock authorization API call
        with patch("httpx.AsyncClient") as mock_client_class:
            # Create mock client instance
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock successful authorization response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={"authorized": True})
            mock_response.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            # Query authorization API
            auth_result = (
                await authorization_service_enterprise.query_authorization_api(
                    user_id=sso_result.user_id,
                    user_email=sso_result.user_email,
                    client_ip="192.168.1.100",
                )
            )

            assert auth_result.authorized is True
            assert auth_result.error is None

        # Step 3: Generate token
        plaintext_token, token_hash = token_service.generate_token()

        # Step 4: Store token in database
        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id=sso_result.user_id,
            user_email=sso_result.user_email,
            provider=sso_result.provider,
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=datetime.now(timezone.utc),
            auth_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        await token_repository.store_token(token_record)

        # Step 5: Verify token can be retrieved and validated
        retrieved_record = await token_repository.find_by_hash(token_hash)
        assert retrieved_record is not None
        assert retrieved_record.user_email == "enterprise@company.com"
        assert retrieved_record.is_authenticated is True

        # Step 6: Verify token service can validate the token
        is_valid = token_service.verify_token(plaintext_token, token_hash)
        assert is_valid is True


class TestReAuthenticationFlow:
    """
    Test 20.2: Re-authentication flow
    Tests expired session -> SSO -> Status update
    Requirements: 5.1, 5.3, 9.3
    """

    @pytest.mark.asyncio
    async def test_expired_session_reauth(
        self,
        token_repository,
        token_service,
        auth_middleware,
    ):
        """Test re-authentication flow when SSO session expires."""
        # Step 1: Create an initial authenticated token
        plaintext_token, token_hash = token_service.generate_token()

        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id="reauth_user_789",
            user_email="reauth@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
            last_authenticated_at=datetime.now(timezone.utc) - timedelta(days=2),
            auth_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
        )

        await token_repository.store_token(token_record)

        # Step 2: Verify token exists but is expired
        retrieved = await token_repository.find_by_hash(token_hash)
        assert retrieved is not None
        assert retrieved.is_authenticated is True  # Still marked as authenticated
        assert retrieved.auth_expires_at < datetime.now(timezone.utc)  # But expired

        # Step 3: Simulate middleware detecting expired session
        mock_request = {
            "headers": {"authorization": f"Bearer {plaintext_token}"},
            "messages": [],
        }

        response = await auth_middleware(mock_request)

        # Should return sandbox response for expired session
        assert response is not None
        assert "choices" in response
        assert "authenticate" in response["choices"][0]["message"]["content"].lower()

        # Step 4: Simulate re-authentication (SSO completes successfully)
        # Update the token's authentication status
        new_expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        await token_repository.update_auth_status(
            token_id=token_record.id,
            authenticated=True,
            expiry=new_expiry,
        )

        # Step 5: Verify token is now re-authenticated
        updated = await token_repository.find_by_hash(token_hash)
        assert updated is not None
        assert updated.is_authenticated is True
        assert updated.auth_expires_at > datetime.now(timezone.utc)
        assert updated.id == token_record.id  # Same token, not a new one

        # Step 6: Verify middleware now allows the request through
        response2 = await auth_middleware(mock_request)
        assert response2 is None  # None means authenticated, continue to next handler

    @pytest.mark.asyncio
    async def test_reauth_preserves_token_id(
        self,
        token_repository,
        token_service,
    ):
        """Test that re-authentication updates existing token, not creates new one."""
        # Step 1: Create initial token
        plaintext_token, token_hash = token_service.generate_token()
        original_id = secrets.token_urlsafe(16)

        token_record = TokenRecord(
            id=original_id,
            token_hash=token_hash,
            user_id="preserve_test_user",
            user_email="preserve@example.com",
            provider="google",
            is_authenticated=False,  # Unauthenticated initially
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=None,
            auth_expires_at=None,
        )

        await token_repository.store_token(token_record)

        # Step 2: Simulate re-authentication
        new_expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        await token_repository.update_auth_status(
            token_id=original_id,
            authenticated=True,
            expiry=new_expiry,
        )

        # Step 3: Verify same token ID is used
        updated = await token_repository.find_by_hash(token_hash)
        assert updated is not None
        assert updated.id == original_id  # Same ID
        assert updated.is_authenticated is True
        assert updated.auth_expires_at is not None


class TestSandboxIsolation:
    """
    Test 20.3: Sandbox isolation
    Tests that sandbox sessions cannot continue after auth
    Requirements: 10.1, 10.2
    """

    @pytest.mark.asyncio
    async def test_sandbox_history_rejection(
        self,
        auth_middleware,
        token_repository,
        token_service,
    ):
        """Test that requests with sandbox history are rejected even with valid token."""
        # Step 1: Create a valid authenticated token
        plaintext_token, token_hash = token_service.generate_token()

        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id="sandbox_test_user",
            user_email="sandbox@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=datetime.now(timezone.utc),
            auth_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        await token_repository.store_token(token_record)

        # Step 2: Create request with sandbox login banner in history
        mock_request = {
            "headers": {"authorization": f"Bearer {plaintext_token}"},
            "messages": [
                {
                    "role": "assistant",
                    "content": "Please authenticate at http://localhost:8080/auth/login to use this proxy.",
                },
                {"role": "user", "content": "I want to write some code"},
            ],
        }

        # Step 3: Middleware should reject due to sandbox history
        response = await auth_middleware(mock_request)

        # Should return sandbox response even though token is valid
        assert response is not None
        assert "choices" in response
        assert "authenticate" in response["choices"][0]["message"]["content"].lower()

    @pytest.mark.asyncio
    async def test_sandbox_isolation_prevents_continuation(
        self,
        auth_middleware,
        token_repository,
        token_service,
    ):
        """Test that sandbox sessions cannot be continued after authentication."""
        # Step 1: Simulate unauthenticated request (no token)
        mock_request_unauth = {
            "headers": {},
            "messages": [{"role": "user", "content": "Hello"}],
        }

        # Get sandbox response
        sandbox_response = await auth_middleware(mock_request_unauth)
        assert sandbox_response is not None
        sandbox_content = sandbox_response["choices"][0]["message"]["content"]
        assert "authenticate" in sandbox_content.lower()

        # Step 2: User authenticates and gets a token
        plaintext_token, token_hash = token_service.generate_token()

        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id="isolation_test_user",
            user_email="isolation@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=datetime.now(timezone.utc),
            auth_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        await token_repository.store_token(token_record)

        # Step 3: User tries to continue the sandbox session with new token
        mock_request_with_history = {
            "headers": {"authorization": f"Bearer {plaintext_token}"},
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": sandbox_content},  # Sandbox banner
                {
                    "role": "user",
                    "content": "Now I'm authenticated, let's continue",
                },
            ],
        }

        # Should be rejected due to sandbox history
        response = await auth_middleware(mock_request_with_history)
        assert response is not None
        assert "authenticate" in response["choices"][0]["message"]["content"].lower()

        # Step 4: User starts fresh conversation with token (no sandbox history)
        mock_request_fresh = {
            "headers": {"authorization": f"Bearer {plaintext_token}"},
            "messages": [{"role": "user", "content": "Hello, I'm starting fresh"}],
        }

        # Should be allowed through
        response_fresh = await auth_middleware(mock_request_fresh)
        assert response_fresh is None  # None means authenticated, continue

    @pytest.mark.asyncio
    async def test_sandbox_detection_various_formats(
        self,
        auth_middleware,
        token_repository,
        token_service,
    ):
        """Test sandbox detection works with various message formats."""
        # Create valid token
        plaintext_token, token_hash = token_service.generate_token()

        token_record = TokenRecord(
            id=secrets.token_urlsafe(16),
            token_hash=token_hash,
            user_id="format_test_user",
            user_email="format@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=datetime.now(timezone.utc),
            auth_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        await token_repository.store_token(token_record)

        # Test various sandbox message formats
        sandbox_messages = [
            "Please authenticate at http://localhost:8080/auth/login",
            "Authentication required. Visit http://localhost:8080/auth/login",
            "To use this proxy, please authenticate at http://localhost:8080/auth/login",
        ]

        for sandbox_msg in sandbox_messages:
            mock_request = {
                "headers": {"authorization": f"Bearer {plaintext_token}"},
                "messages": [
                    {"role": "assistant", "content": sandbox_msg},
                    {"role": "user", "content": "Continue"},
                ],
            }

            response = await auth_middleware(mock_request)
            assert (
                response is not None
            ), f"Failed to detect sandbox message: {sandbox_msg}"
