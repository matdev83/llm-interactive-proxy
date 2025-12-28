"""Unit tests for SSO repository implementations."""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from src.core.auth.sso.models import TokenRecord
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.database.repositories.sso_repository import (
    SQLModelAuthorizationRepository,
    SQLModelRateLimitRepository,
    SQLModelTokenRepository,
)


class TestSQLModelTokenRepository:
    """Tests for SQLModelTokenRepository."""

    @pytest.fixture
    async def engine(self) -> DatabaseEngine:
        """Create in-memory database engine for testing."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        engine = DatabaseEngine(config)
        await engine.initialize()
        yield engine
        await engine.close()

    @pytest.fixture
    def repository(self, engine: DatabaseEngine) -> SQLModelTokenRepository:
        """Create token repository for testing."""
        return SQLModelTokenRepository(engine)

    @pytest.fixture
    def sample_token_record(self) -> TokenRecord:
        """Create a sample token record for testing."""
        with freeze_time("2024-01-01 12:00:00"):
            return TokenRecord(
                id="token-123",
                token_hash="hash-abc-123",
                user_id="user-456",
                user_email="user@example.com",
                provider="google",
                is_authenticated=False,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                last_authenticated_at=None,
                auth_expires_at=None,
            )

    @pytest.mark.asyncio
    async def test_store_and_get_token(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test storing and retrieving a token."""
        await repository.store_token(sample_token_record)

        retrieved = await repository.get_token_by_id(sample_token_record.id)

        assert retrieved is not None
        assert retrieved.id == sample_token_record.id
        assert retrieved.token_hash == sample_token_record.token_hash
        assert retrieved.user_id == sample_token_record.user_id
        assert retrieved.user_email == sample_token_record.user_email
        assert retrieved.provider == sample_token_record.provider

    @pytest.mark.asyncio
    async def test_get_token_by_id_returns_none_for_missing(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test that get_token_by_id returns None for missing tokens."""
        result = await repository.get_token_by_id("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_user_id(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test finding token by user ID."""
        await repository.store_token(sample_token_record)

        retrieved = await repository.find_by_user_id(sample_token_record.user_id)

        assert retrieved is not None
        assert retrieved.user_id == sample_token_record.user_id

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_find_by_user_id_returns_most_recent(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test that find_by_user_id returns most recent token."""
        user_id = "user-recent-test"

        # Create older token
        old_token = TokenRecord(
            id="token-old",
            token_hash="hash-old",
            user_id=user_id,
            user_email="user@test.com",
            provider="google",
            is_authenticated=False,
            is_active=True,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        await repository.store_token(old_token)

        # Create newer token
        new_token = TokenRecord(
            id="token-new",
            token_hash="hash-new",
            user_id=user_id,
            user_email="user@test.com",
            provider="google",
            is_authenticated=False,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        await repository.store_token(new_token)

        retrieved = await repository.find_by_user_id(user_id)

        assert retrieved is not None
        assert retrieved.id == "token-new"

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_find_by_user_id_ignores_inactive(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test that find_by_user_id ignores inactive tokens."""
        user_id = "user-inactive-test"

        # Create inactive token
        inactive_token = TokenRecord(
            id="token-inactive",
            token_hash="hash-inactive",
            user_id=user_id,
            user_email="user@test.com",
            provider="google",
            is_authenticated=False,
            is_active=False,
            created_at=datetime.now(timezone.utc),
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        await repository.store_token(inactive_token)

        retrieved = await repository.find_by_user_id(user_id)

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_hash(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test finding token by hash with constant-time comparison."""
        await repository.store_token(sample_token_record)

        retrieved = await repository.find_by_hash(sample_token_record.token_hash)

        assert retrieved is not None
        assert retrieved.token_hash == sample_token_record.token_hash

    @pytest.mark.asyncio
    async def test_find_by_hash_returns_none_for_wrong_hash(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test that find_by_hash returns None for wrong hash."""
        await repository.store_token(sample_token_record)

        retrieved = await repository.find_by_hash("wrong-hash")

        assert retrieved is None

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_update_auth_status(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test updating authentication status."""
        await repository.store_token(sample_token_record)

        expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        await repository.update_auth_status(
            token_id=sample_token_record.id,
            authenticated=True,
            expiry=expiry,
        )

        retrieved = await repository.get_token_by_id(sample_token_record.id)

        assert retrieved is not None
        assert retrieved.is_authenticated is True
        assert retrieved.auth_expires_at is not None

    @pytest.mark.asyncio
    async def test_revoke_token(
        self,
        repository: SQLModelTokenRepository,
        sample_token_record: TokenRecord,
    ) -> None:
        """Test revoking a token (soft delete)."""
        await repository.store_token(sample_token_record)

        await repository.revoke_token(sample_token_record.id)

        retrieved = await repository.get_token_by_id(sample_token_record.id)

        assert retrieved is not None
        assert retrieved.is_active is False

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_get_all_token_hashes(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test getting all active token hashes."""
        # Create multiple tokens
        for i in range(3):
            token = TokenRecord(
                id=f"token-{i}",
                token_hash=f"hash-{i}",
                user_id=f"user-{i}",
                user_email=f"user{i}@test.com",
                provider="google",
                is_authenticated=False,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                last_authenticated_at=None,
                auth_expires_at=None,
            )
            await repository.store_token(token)

        hashes = await repository.get_all_token_hashes()

        assert len(hashes) == 3
        assert "hash-0" in hashes
        assert "hash-1" in hashes
        assert "hash-2" in hashes

    @pytest.mark.asyncio
    async def test_create_login_token(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test creating a login token."""
        token = await repository.create_login_token(ttl_minutes=10)

        assert token is not None
        assert len(token) > 20  # URL-safe token

    @pytest.mark.asyncio
    async def test_create_login_token_with_agent_token_id(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test creating a login token linked to an agent token."""
        token = await repository.create_login_token(
            ttl_minutes=10,
            agent_token_id="agent-token-123",
        )

        assert token is not None

    @pytest.mark.asyncio
    async def test_verify_and_consume_login_token(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test verifying and consuming a login token."""
        token = await repository.create_login_token(ttl_minutes=10)

        is_valid, agent_id = await repository.verify_and_consume_login_token(token)

        assert is_valid is True
        assert agent_id is None

        # Token should be consumed (second call fails)
        is_valid_again, _ = await repository.verify_and_consume_login_token(token)
        assert is_valid_again is False

    @pytest.mark.asyncio
    async def test_verify_and_consume_returns_agent_token_id(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test that verify returns agent_token_id if set."""
        token = await repository.create_login_token(
            ttl_minutes=10,
            agent_token_id="agent-123",
        )

        is_valid, agent_id = await repository.verify_and_consume_login_token(token)

        assert is_valid is True
        assert agent_id == "agent-123"

    @pytest.mark.asyncio
    async def test_verify_invalid_token(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test verifying an invalid token."""
        is_valid, agent_id = await repository.verify_and_consume_login_token(
            "invalid-token"
        )

        assert is_valid is False
        assert agent_id is None

    @pytest.mark.asyncio
    async def test_verify_empty_token(
        self,
        repository: SQLModelTokenRepository,
    ) -> None:
        """Test verifying an empty token."""
        is_valid, agent_id = await repository.verify_and_consume_login_token("")

        assert is_valid is False


class TestSQLModelRateLimitRepository:
    """Tests for SQLModelRateLimitRepository."""

    @pytest.fixture
    async def engine(self) -> DatabaseEngine:
        """Create in-memory database engine for testing."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        engine = DatabaseEngine(config)
        await engine.initialize()
        yield engine
        await engine.close()

    @pytest.fixture
    def repository(self, engine: DatabaseEngine) -> SQLModelRateLimitRepository:
        """Create rate limit repository for testing."""
        return SQLModelRateLimitRepository(engine)

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed_initially(
        self,
        repository: SQLModelRateLimitRepository,
    ) -> None:
        """Test that new identifiers are not rate limited."""
        result = await repository.check_rate_limit("192.168.1.1")

        assert result.allowed is True
        assert result.retry_after == 0

    @pytest.mark.asyncio
    async def test_record_failed_attempt(
        self,
        repository: SQLModelRateLimitRepository,
    ) -> None:
        """Test recording a failed attempt."""
        identifier = "192.168.1.2"

        await repository.record_failed_attempt(identifier)

        result = await repository.check_rate_limit(identifier)

        # Should be blocked after first failure
        assert result.allowed is False
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_exponential_backoff(
        self,
        repository: SQLModelRateLimitRepository,
    ) -> None:
        """Test that backoff increases exponentially."""
        identifier = "192.168.1.3"

        # First failure: 2s backoff
        await repository.record_failed_attempt(identifier)
        result1 = await repository.check_rate_limit(identifier)

        # Second failure: 4s backoff
        await repository.record_failed_attempt(identifier)
        result2 = await repository.check_rate_limit(identifier)

        # Third failure: 8s backoff
        await repository.record_failed_attempt(identifier)
        result3 = await repository.check_rate_limit(identifier)

        # Each should have longer backoff (accounting for timing variations)
        assert result2.retry_after >= result1.retry_after
        assert result3.retry_after >= result2.retry_after

    @pytest.mark.asyncio
    async def test_reset_rate_limit(
        self,
        repository: SQLModelRateLimitRepository,
    ) -> None:
        """Test resetting rate limit."""
        identifier = "192.168.1.4"

        # Create a rate limit
        await repository.record_failed_attempt(identifier)

        # Verify blocked
        result = await repository.check_rate_limit(identifier)
        assert result.allowed is False

        # Reset
        await repository.reset_rate_limit(identifier)

        # Should be allowed again
        result = await repository.check_rate_limit(identifier)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_reset_nonexistent_is_safe(
        self,
        repository: SQLModelRateLimitRepository,
    ) -> None:
        """Test that resetting nonexistent identifier is safe."""
        # Should not raise
        await repository.reset_rate_limit("nonexistent-identifier")


class TestSQLModelAuthorizationRepository:
    """Tests for SQLModelAuthorizationRepository."""

    @pytest.fixture
    async def engine(self) -> DatabaseEngine:
        """Create in-memory database engine for testing."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        engine = DatabaseEngine(config)
        await engine.initialize()
        yield engine
        await engine.close()

    @pytest.fixture
    def repository(self, engine: DatabaseEngine) -> SQLModelAuthorizationRepository:
        """Create authorization repository for testing."""
        return SQLModelAuthorizationRepository(engine)

    @pytest.mark.asyncio
    async def test_create_and_get_pending(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test creating and retrieving a pending authorization."""
        await repository.create_pending(
            id="auth-123",
            sso_state="state-abc",
            user_email="user@example.com",
            user_id="user-456",
            provider="google",
            confirmation_code_hash="hash-xyz",
            max_attempts=3,
            expiry_minutes=10,
            client_ip="192.168.1.1",
        )

        result = await repository.get_by_sso_state("state-abc")

        assert result is not None
        assert result.id == "auth-123"
        assert result.sso_state == "state-abc"
        assert result.user_email == "user@example.com"
        assert result.user_id == "user-456"
        assert result.provider == "google"
        assert result.confirmation_code_hash == "hash-xyz"
        assert result.attempts_remaining == 3
        assert result.client_ip == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_get_by_sso_state_returns_none_for_missing(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test that get_by_sso_state returns None for missing state."""
        result = await repository.get_by_sso_state("nonexistent-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_by_sso_state(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test deleting by SSO state."""
        await repository.create_pending(
            id="auth-delete",
            sso_state="state-delete",
            user_email="user@example.com",
            user_id="user-456",
            provider="google",
            confirmation_code_hash="hash",
            max_attempts=3,
            expiry_minutes=10,
            client_ip="127.0.0.1",
        )

        await repository.delete_by_sso_state("state-delete")

        result = await repository.get_by_sso_state("state-delete")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_safe(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test that deleting nonexistent state is safe."""
        # Should not raise
        await repository.delete_by_sso_state("nonexistent-state")

    @pytest.mark.asyncio
    async def test_decrement_attempts(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test decrementing attempts remaining."""
        await repository.create_pending(
            id="auth-dec",
            sso_state="state-dec",
            user_email="user@example.com",
            user_id="user-456",
            provider="google",
            confirmation_code_hash="hash",
            max_attempts=3,
            expiry_minutes=10,
            client_ip="127.0.0.1",
        )

        # Decrement
        remaining = await repository.decrement_attempts("state-dec")
        assert remaining == 2

        remaining = await repository.decrement_attempts("state-dec")
        assert remaining == 1

        remaining = await repository.decrement_attempts("state-dec")
        assert remaining == 0

        # Should not go below 0
        remaining = await repository.decrement_attempts("state-dec")
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_decrement_nonexistent_returns_zero(
        self,
        repository: SQLModelAuthorizationRepository,
    ) -> None:
        """Test that decrementing nonexistent returns 0."""
        remaining = await repository.decrement_attempts("nonexistent-state")
        assert remaining == 0
