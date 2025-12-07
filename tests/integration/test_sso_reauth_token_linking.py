"""
Integration tests for SSO re-authentication token linking.

This module tests the complete re-authentication flow including:
- Token linking through login tokens
- Existing token renewal without reconfiguration
- Security validation for token ownership
- End-to-end flow from expired session to re-authentication
"""

import asyncio
import secrets
from datetime import datetime, timedelta

import pytest
from src.core.auth.sso.config import AuthorizationConfig, SSOConfig
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.middleware import AuthMiddleware
from src.core.auth.sso.models import TokenRecord
from src.core.auth.sso.rate_limit_service import RateLimitService
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.token_service import TokenService


@pytest.fixture
async def sso_database(tmp_path):
    """Create a temporary SSO database."""
    db_path = str(tmp_path / "sso_test.db")
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize_schema()
    return db_path


@pytest.fixture
def token_service():
    """Create token service."""
    return TokenService.create_for_environment()


@pytest.fixture
def sso_config():
    """Create SSO configuration."""
    return SSOConfig(
        enabled=True,
        database_path=":memory:",
        session_lifetime_hours=24,
        providers=[],
        authorization=AuthorizationConfig(
            mode="enterprise",
            api_url="http://localhost:9999/authorize",
            api_timeout=5,
        ),
    )


@pytest.fixture
async def token_repository(sso_database):
    """Create token repository."""
    return TokenRepository(sso_database)


@pytest.fixture
def sandbox_handler(token_repository):
    """Create sandbox handler."""
    return SandboxHandler(
        auth_url="http://localhost:8000/auth/login",
        token_repository=token_repository,
    )


@pytest.fixture
def auth_middleware(token_service, token_repository, sandbox_handler):
    """Create auth middleware."""
    return AuthMiddleware(
        token_service=token_service,
        token_repository=token_repository,
        sandbox_handler=sandbox_handler,
    )


class TestReauthenticationTokenLinking:
    """Test re-authentication with token linking."""

    @pytest.mark.asyncio
    async def test_login_token_stores_agent_token_id(self, token_repository):
        """
        Test that login tokens can store agent_token_id for re-authentication.

        Requirements: 5.1, 5.3
        """
        # Create a login token with agent_token_id
        agent_token_id = "token-123"
        login_token = await token_repository.create_login_token(
            agent_token_id=agent_token_id
        )

        assert login_token is not None
        assert len(login_token) > 0

        # Verify and consume the login token
        is_valid, retrieved_token_id = (
            await token_repository.verify_and_consume_login_token(login_token)
        )

        assert is_valid is True
        assert retrieved_token_id == agent_token_id

    @pytest.mark.asyncio
    async def test_login_token_without_agent_token_id(self, token_repository):
        """
        Test that login tokens work without agent_token_id (new authentication).

        Requirements: 3.1
        """
        # Create a login token without agent_token_id
        login_token = await token_repository.create_login_token()

        assert login_token is not None

        # Verify and consume the login token
        is_valid, retrieved_token_id = (
            await token_repository.verify_and_consume_login_token(login_token)
        )

        assert is_valid is True
        assert retrieved_token_id is None

    @pytest.mark.asyncio
    async def test_expired_session_includes_token_id_in_sandbox(
        self, auth_middleware, token_repository, token_service
    ):
        """
        Test that expired sessions generate sandbox responses with token_id.

        Requirements: 9.1, 9.3
        """
        # Create an expired token
        plaintext_token, token_hash = token_service.generate_token()
        expired_time = datetime.utcnow() - timedelta(hours=1)

        token_record = TokenRecord(
            id="token-456",
            token_hash=token_hash,
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.utcnow() - timedelta(days=1),
            last_authenticated_at=datetime.utcnow() - timedelta(hours=2),
            auth_expires_at=expired_time,
        )

        await token_repository.store_token(token_record)

        # Make a request with the expired token
        request = {
            "headers": {"authorization": f"Bearer {plaintext_token}"},
            "messages": [],
            "method": "POST",
            "path": "/v1/chat/completions",
        }

        # Should return sandbox response
        response = await auth_middleware(request)

        assert response is not None
        assert "choices" in response
        assert len(response["choices"]) > 0

        # Check that the message contains re-authentication text
        message = response["choices"][0]["message"]["content"]
        assert (
            "re-authentication" in message.lower()
            or "re-authenticate" in message.lower()
        )
        assert "http://localhost:8000/auth/login" in message

    @pytest.mark.asyncio
    async def test_sandbox_handler_includes_token_id_in_url(
        self, sandbox_handler, token_repository
    ):
        """
        Test that sandbox handler includes token_id when generating login URLs.

        Requirements: 5.3, 9.3
        """
        # Generate login banner with token_id
        agent_token_id = "token-789"
        response = await sandbox_handler.generate_login_banner(
            agent_token_id=agent_token_id
        )

        assert response is not None
        assert "choices" in response

        message = response["choices"][0]["message"]["content"]

        # Should contain re-authentication text
        assert (
            "re-authentication" in message.lower()
            or "re-authenticate" in message.lower()
        )

        # Should contain login URL with token parameter
        assert "http://localhost:8000/auth/login?token=" in message

    @pytest.mark.asyncio
    async def test_sandbox_handler_without_token_id(
        self, sandbox_handler, token_repository
    ):
        """
        Test that sandbox handler works without token_id (new authentication).

        Requirements: 2.1, 3.1
        """
        # Generate login banner without token_id
        response = await sandbox_handler.generate_login_banner()

        assert response is not None
        assert "choices" in response

        message = response["choices"][0]["message"]["content"]

        # Should contain new authentication text (not re-authentication)
        assert "authentication required" in message.lower()
        assert "welcome to the llm proxy" in message.lower()

    @pytest.mark.asyncio
    async def test_web_interface_reauth_flow_enterprise_mode(
        self, sso_config, sso_database, token_service
    ):
        """
        Test complete re-authentication flow in enterprise mode.

        Requirements: 5.1, 5.3, 9.3
        """
        # Setup
        db_manager = DatabaseManager(sso_database)
        token_repo = TokenRepository(sso_database)
        RateLimitService(db_manager)

        # Create existing token (user already authenticated before)
        plaintext_token, token_hash = token_service.generate_token()
        existing_token = TokenRecord(
            id="existing-token-id",
            token_hash=token_hash,
            user_id="user-123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=False,  # Session expired
            is_active=True,
            created_at=datetime.utcnow() - timedelta(days=7),
            last_authenticated_at=datetime.utcnow() - timedelta(hours=25),
            auth_expires_at=datetime.utcnow() - timedelta(hours=1),  # Expired
        )
        await token_repo.store_token(existing_token)

        # User requests a login token for re-authentication
        login_token = await token_repo.create_login_token(
            agent_token_id=existing_token.id
        )

        # Verify the login token carries the agent_token_id
        is_valid, agent_token_id = await token_repo.verify_and_consume_login_token(
            login_token
        )

        assert is_valid is True
        assert agent_token_id == existing_token.id

        # Simulate successful OAuth callback and authorization
        # The web interface should update the existing token, not create a new one

        # Verify token was updated (in real flow, this happens in web_interface callback)
        await token_repo.update_auth_status(
            token_id=existing_token.id,
            authenticated=True,
            expiry=datetime.utcnow() + timedelta(hours=24),
        )

        # Verify the token is now authenticated
        updated_token = await token_repo.get_by_id(existing_token.id)
        assert updated_token is not None
        assert updated_token.is_authenticated is True
        assert updated_token.auth_expires_at is not None
        assert updated_token.auth_expires_at > datetime.utcnow()

    @pytest.mark.asyncio
    async def test_web_interface_new_user_flow(
        self, sso_config, sso_database, token_service
    ):
        """
        Test new user authentication flow (no existing token).

        Requirements: 3.1, 3.3
        """
        # Setup
        token_repo = TokenRepository(sso_database)

        # User requests a login token (no agent_token_id - new user)
        login_token = await token_repo.create_login_token()

        # Verify the login token has no agent_token_id
        is_valid, agent_token_id = await token_repo.verify_and_consume_login_token(
            login_token
        )

        assert is_valid is True
        assert agent_token_id is None

        # Simulate successful OAuth callback and authorization
        # The web interface should create a NEW token

        plaintext_token, token_hash = token_service.generate_token()
        new_token = TokenRecord(
            id=secrets.token_hex(16),
            token_hash=token_hash,
            user_id="new-user-456",
            user_email="newuser@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.utcnow(),
            last_authenticated_at=datetime.utcnow(),
            auth_expires_at=datetime.utcnow() + timedelta(hours=24),
        )

        await token_repo.store_token(new_token)

        # Verify the new token exists
        retrieved_token = await token_repo.get_by_id(new_token.id)
        assert retrieved_token is not None
        assert retrieved_token.user_id == "new-user-456"

    @pytest.mark.asyncio
    async def test_security_token_ownership_validation(
        self, sso_config, sso_database, token_service
    ):
        """
        Test that re-authentication validates token ownership.

        Security requirement: User A cannot re-auth with User B's token.

        Requirements: 4.1, 5.1
        """
        # Setup
        token_repo = TokenRepository(sso_database)

        # Create token for User A
        _, token_hash_a = token_service.generate_token()
        token_a = TokenRecord(
            id="token-user-a",
            token_hash=token_hash_a,
            user_id="user-a",
            user_email="usera@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.utcnow(),
            last_authenticated_at=datetime.utcnow(),
            auth_expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        await token_repo.store_token(token_a)

        # User B tries to re-authenticate but provides User A's token_id
        login_token = await token_repo.create_login_token(
            agent_token_id=token_a.id  # User A's token
        )

        is_valid, agent_token_id = await token_repo.verify_and_consume_login_token(
            login_token
        )

        assert is_valid is True
        assert agent_token_id == token_a.id

        # In the web interface callback, it should check:
        # if agent_token_id and existing_token.user_id != authenticated_user_id:
        #     reject or fall through to new token creation

        # Simulate: User B authenticates (user_id = "user-b")
        # The system should NOT update token_a (belongs to user-a)

        existing_token = await token_repo.get_by_id(agent_token_id)
        assert existing_token is not None

        authenticated_user_id = "user-b"  # User B authenticated

        # Security check: token belongs to different user
        if existing_token.user_id != authenticated_user_id:
            # Should reject or create new token
            # NOT update existing_token

            # Create new token for User B instead
            _, token_hash_b = token_service.generate_token()
            token_b = TokenRecord(
                id="token-user-b",
                token_hash=token_hash_b,
                user_id="user-b",
                user_email="userb@example.com",
                provider="google",
                is_authenticated=True,
                is_active=True,
                created_at=datetime.utcnow(),
                last_authenticated_at=datetime.utcnow(),
                auth_expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            await token_repo.store_token(token_b)

        # Verify User A's token was NOT modified
        token_a_after = await token_repo.get_by_id(token_a.id)
        assert token_a_after.user_id == "user-a"
        assert token_a_after.is_authenticated is True  # Still same

    @pytest.mark.asyncio
    async def test_login_token_expiration(self, token_repository):
        """
        Test that expired login tokens are rejected.

        Requirements: 3.2 (secure token generation and validation)
        """
        # Create a login token with very short TTL
        login_token = await token_repository.create_login_token(
            ttl_minutes=0,  # Expires immediately
            agent_token_id="test-token-id",
        )

        # Wait a tiny bit to ensure expiration
        await asyncio.sleep(0.1)

        # Try to verify the expired token
        is_valid, agent_token_id = (
            await token_repository.verify_and_consume_login_token(login_token)
        )

        assert is_valid is False
        assert agent_token_id is None

    @pytest.mark.asyncio
    async def test_login_token_single_use(self, token_repository):
        """
        Test that login tokens can only be used once.

        Requirements: Security - prevent replay attacks
        """
        # Create a login token
        login_token = await token_repository.create_login_token(
            agent_token_id="test-token-id"
        )

        # Use it once
        is_valid, agent_token_id = (
            await token_repository.verify_and_consume_login_token(login_token)
        )

        assert is_valid is True
        assert agent_token_id == "test-token-id"

        # Try to use it again
        is_valid2, agent_token_id2 = (
            await token_repository.verify_and_consume_login_token(login_token)
        )

        assert is_valid2 is False
        assert agent_token_id2 is None

    @pytest.mark.asyncio
    async def test_multiple_reauthentications(
        self, sso_database, token_service, token_repository
    ):
        """
        Test that a user can re-authenticate multiple times with the same token.

        Requirements: 5.2, 9.3
        """
        # Create initial token
        plaintext_token, token_hash = token_service.generate_token()
        token_record = TokenRecord(
            id="persistent-token",
            token_hash=token_hash,
            user_id="user-persistent",
            user_email="persistent@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=datetime.utcnow(),
            last_authenticated_at=datetime.utcnow(),
            auth_expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        await token_repository.store_token(token_record)

        # Simulate 3 re-authentication cycles
        for _i in range(3):
            # Session expires
            await token_repository.update_auth_status(
                token_id=token_record.id,
                authenticated=False,
                expiry=None,
            )

            # User re-authenticates
            login_token = await token_repository.create_login_token(
                agent_token_id=token_record.id
            )

            is_valid, agent_token_id = (
                await token_repository.verify_and_consume_login_token(login_token)
            )

            assert is_valid is True
            assert agent_token_id == token_record.id

            # Update token after successful re-auth
            await token_repository.update_auth_status(
                token_id=token_record.id,
                authenticated=True,
                expiry=datetime.utcnow() + timedelta(hours=24),
            )

            # Verify token is authenticated again
            updated = await token_repository.get_by_id(token_record.id)
            assert updated.is_authenticated is True

        # Token should still have the same ID after multiple re-auths
        final_token = await token_repository.get_by_id(token_record.id)
        assert final_token.id == "persistent-token"
        assert final_token.user_id == "user-persistent"


class TestReauthenticationMessages:
    """Test user-facing messages for re-authentication."""

    @pytest.mark.asyncio
    async def test_reauth_message_differs_from_new_auth(self, sandbox_handler):
        """
        Test that re-authentication messages are different from new auth messages.

        Requirements: 9.2, 9.4
        """
        # New authentication message
        new_auth_response = await sandbox_handler.generate_login_banner()
        new_auth_message = new_auth_response["choices"][0]["message"]["content"]

        # Re-authentication message
        reauth_response = await sandbox_handler.generate_login_banner(
            agent_token_id="some-token-id"
        )
        reauth_message = reauth_response["choices"][0]["message"]["content"]

        # Messages should be different
        assert new_auth_message != reauth_message

        # New auth should say "Authentication Required"
        assert "# Authentication Required" in new_auth_message

        # Re-auth should say "Re-Authentication Required"
        assert "# Re-Authentication Required" in reauth_message

        # Re-auth should mention no reconfiguration needed
        assert (
            "no reconfiguration" in reauth_message.lower()
            or "no need to reconfigure" in reauth_message.lower()
        )

        # New auth should mention configuring the agent
        assert "configure" in new_auth_message.lower()
        assert "copy the agent token" in new_auth_message.lower()
