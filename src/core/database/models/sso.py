"""SQLModel models for SSO authentication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    pass


class SchemaVersionTable(SQLModel, table=True):
    """SQLModel table for schema version tracking.

    Tracks database schema versions for migration purposes.
    """

    __tablename__ = "schema_version"

    version: int = Field(primary_key=True)
    applied_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AgentTokenTable(SQLModel, table=True):
    """SQLModel table for agent authentication tokens.

    Stores tokens used by AI agents to authenticate with the proxy.
    """

    __tablename__ = "agent_tokens"

    id: str = Field(primary_key=True, max_length=64)
    token_hash: str = Field(nullable=False, unique=True, max_length=256)
    user_id: str = Field(nullable=False, index=True, max_length=256)
    user_email: str = Field(nullable=False, max_length=512)
    provider: str = Field(nullable=False, max_length=64)

    # Authentication state
    is_authenticated: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False, index=True)

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_authenticated_at: datetime | None = Field(default=None)
    auth_expires_at: datetime | None = Field(default=None)

    __table_args__ = (Index("idx_agent_tokens_token_hash", "token_hash"),)


class PendingAuthorizationTable(SQLModel, table=True):
    """SQLModel table for pending SSO authorizations.

    Stores pending authorization requests with confirmation codes.
    """

    __tablename__ = "pending_authorizations"

    id: str = Field(primary_key=True, max_length=64)
    sso_state: str = Field(nullable=False, unique=True, max_length=256)

    # User info
    user_email: str = Field(nullable=False, max_length=512)
    user_id: str = Field(nullable=False, max_length=256)
    provider: str = Field(nullable=False, max_length=64)

    # Confirmation
    confirmation_code_hash: str = Field(nullable=False, max_length=256)
    attempts_remaining: int = Field(default=3, nullable=False)

    # Timestamps and context
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: datetime = Field(nullable=False)
    client_ip: str = Field(nullable=False, max_length=64)

    __table_args__ = (Index("idx_pending_auth_sso_state", "sso_state"),)


class RateLimitTable(SQLModel, table=True):
    """SQLModel table for rate limiting.

    Tracks failed attempts and blocks for rate limiting.
    """

    __tablename__ = "rate_limits"

    identifier: str = Field(primary_key=True, max_length=256)
    failed_attempts: int = Field(default=0, nullable=False)
    last_attempt_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    blocked_until: datetime | None = Field(default=None)


class SSOLoginTokenTable(SQLModel, table=True):
    """SQLModel table for one-off SSO login tokens.

    Stores temporary tokens for SSO login link validation.
    """

    __tablename__ = "sso_login_tokens"

    token: str = Field(primary_key=True, max_length=256)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: datetime = Field(nullable=False)
    agent_token_id: str | None = Field(default=None, max_length=64, index=True)

    __table_args__ = (Index("idx_login_token_agent_token", "agent_token_id"),)
