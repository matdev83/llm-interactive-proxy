"""Unit tests for SSO SQLModel table models."""

from datetime import datetime, timedelta, timezone

from freezegun import freeze_time
from sqlmodel import SQLModel
from src.core.database.models.sso import (
    AgentTokenTable,
    PendingAuthorizationTable,
    RateLimitTable,
    SchemaVersionTable,
    SSOLoginTokenTable,
)


class TestSchemaVersionTable:
    """Tests for SchemaVersionTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert SchemaVersionTable.__tablename__ == "schema_version"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(SchemaVersionTable, SQLModel)
        assert hasattr(SchemaVersionTable, "__table__")

    def test_create_record(self) -> None:
        """Test creating a schema version record."""
        record = SchemaVersionTable(version=1)

        assert record.version == 1
        assert record.applied_at is not None

    def test_create_with_custom_timestamp(self) -> None:
        """Test creating with custom applied_at."""
        custom_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = SchemaVersionTable(version=2, applied_at=custom_time)

        assert record.version == 2
        assert record.applied_at == custom_time


class TestAgentTokenTable:
    """Tests for AgentTokenTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert AgentTokenTable.__tablename__ == "agent_tokens"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(AgentTokenTable, SQLModel)
        assert hasattr(AgentTokenTable, "__table__")

    def test_create_minimal_record(self) -> None:
        """Test creating a record with required fields."""
        record = AgentTokenTable(
            id="token-id-123",
            token_hash="hash123",
            user_id="user-456",
            user_email="user@example.com",
            provider="google",
        )

        assert record.id == "token-id-123"
        assert record.token_hash == "hash123"
        assert record.user_id == "user-456"
        assert record.user_email == "user@example.com"
        assert record.provider == "google"

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        record = AgentTokenTable(
            id="token-id",
            token_hash="hash",
            user_id="user",
            user_email="user@test.com",
            provider="google",
        )

        assert record.is_authenticated is False
        assert record.is_active is True
        assert record.last_authenticated_at is None
        assert record.auth_expires_at is None

    @freeze_time("2024-01-01 12:00:00")
    def test_create_with_auth_fields(self) -> None:
        """Test creating with authentication fields."""
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        expiry = now + timedelta(hours=24)

        record = AgentTokenTable(
            id="token-id",
            token_hash="hash",
            user_id="user",
            user_email="user@test.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=now,
            last_authenticated_at=now,
            auth_expires_at=expiry,
        )

        assert record.is_authenticated is True
        assert record.last_authenticated_at == now
        assert record.auth_expires_at == expiry

    def test_has_required_indexes(self) -> None:
        """Test that model defines required indexes."""
        table_args = AgentTokenTable.__table_args__
        assert table_args is not None

        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_agent_tokens_token_hash" in index_names


class TestPendingAuthorizationTable:
    """Tests for PendingAuthorizationTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert PendingAuthorizationTable.__tablename__ == "pending_authorizations"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(PendingAuthorizationTable, SQLModel)
        assert hasattr(PendingAuthorizationTable, "__table__")

    @freeze_time("2024-01-01 12:00:00")
    def test_create_record(self) -> None:
        """Test creating a pending authorization record."""
        expires = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
            minutes=10
        )
        record = PendingAuthorizationTable(
            id="auth-id-123",
            sso_state="state-abc",
            user_email="user@example.com",
            user_id="user-456",
            provider="google",
            confirmation_code_hash="code-hash",
            expires_at=expires,
            client_ip="192.168.1.1",
        )

        assert record.id == "auth-id-123"
        assert record.sso_state == "state-abc"
        assert record.user_email == "user@example.com"
        assert record.user_id == "user-456"
        assert record.provider == "google"
        assert record.confirmation_code_hash == "code-hash"
        assert record.expires_at == expires
        assert record.client_ip == "192.168.1.1"

    @freeze_time("2024-01-01 12:00:00")
    def test_default_attempts_remaining(self) -> None:
        """Test default value for attempts_remaining."""
        record = PendingAuthorizationTable(
            id="auth-id",
            sso_state="state",
            user_email="user@test.com",
            user_id="user",
            provider="google",
            confirmation_code_hash="hash",
            expires_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            client_ip="127.0.0.1",
        )

        assert record.attempts_remaining == 3

    def test_has_required_indexes(self) -> None:
        """Test that model defines required indexes."""
        table_args = PendingAuthorizationTable.__table_args__
        assert table_args is not None

        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_pending_auth_sso_state" in index_names


class TestRateLimitTable:
    """Tests for RateLimitTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert RateLimitTable.__tablename__ == "rate_limits"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(RateLimitTable, SQLModel)
        assert hasattr(RateLimitTable, "__table__")

    def test_create_record(self) -> None:
        """Test creating a rate limit record."""
        record = RateLimitTable(identifier="192.168.1.1")

        assert record.identifier == "192.168.1.1"
        assert record.failed_attempts == 0
        assert record.blocked_until is None

    @freeze_time("2024-01-01 12:00:00")
    def test_create_with_all_fields(self) -> None:
        """Test creating with all fields."""
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        blocked_until = now + timedelta(hours=1)

        record = RateLimitTable(
            identifier="192.168.1.1",
            failed_attempts=5,
            last_attempt_at=now,
            blocked_until=blocked_until,
        )

        assert record.failed_attempts == 5
        assert record.last_attempt_at == now
        assert record.blocked_until == blocked_until


class TestSSOLoginTokenTable:
    """Tests for SSOLoginTokenTable model."""

    def test_table_name(self) -> None:
        """Test that table name is correct."""
        assert SSOLoginTokenTable.__tablename__ == "sso_login_tokens"

    def test_is_sqlmodel_table(self) -> None:
        """Test that model is properly configured as a SQLModel table."""
        assert issubclass(SSOLoginTokenTable, SQLModel)
        assert hasattr(SSOLoginTokenTable, "__table__")

    @freeze_time("2024-01-01 12:00:00")
    def test_create_record(self) -> None:
        """Test creating a login token record."""
        expires = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
            minutes=10
        )
        record = SSOLoginTokenTable(
            token="token-abc-123",
            expires_at=expires,
        )

        assert record.token == "token-abc-123"
        assert record.expires_at == expires
        assert record.agent_token_id is None

    @freeze_time("2024-01-01 12:00:00")
    def test_create_with_agent_token_id(self) -> None:
        """Test creating with agent_token_id for re-auth."""
        expires = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
            minutes=10
        )
        record = SSOLoginTokenTable(
            token="token-xyz",
            expires_at=expires,
            agent_token_id="agent-token-123",
        )

        assert record.agent_token_id == "agent-token-123"

    def test_has_required_indexes(self) -> None:
        """Test that model defines required indexes."""
        table_args = SSOLoginTokenTable.__table_args__
        assert table_args is not None

        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_login_token_agent_token" in index_names
