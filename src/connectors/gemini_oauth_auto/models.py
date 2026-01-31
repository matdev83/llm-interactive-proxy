"""
Pydantic models for Gemini OAuth Auto-Connector.

Provides data models for OAuth credential storage and account management.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.connectors.gemini_oauth_auto.constants import (
    ACCOUNT_ID_MAX_LENGTH,
    ACCOUNT_ID_PATTERN,
)

# Compiled pattern for validation
_ACCOUNT_ID_REGEX = re.compile(ACCOUNT_ID_PATTERN)


class StoredAccount(BaseModel):
    """OAuth credentials for a stored Google account.

    Follows Google OAuth2 Credentials format with extended fields for
    account management and tracking.

    Attributes:
        account_id: User-specified or auto-generated identifier
        email: Google account email (from userinfo endpoint)
        access_token: Current OAuth access token
        refresh_token: Long-lived refresh token
        token_type: Token type (typically "Bearer")
        scope: Space-separated list of granted scopes
        expiry_date: Token expiry timestamp in milliseconds since epoch
        created_at: ISO 8601 timestamp of initial registration
        updated_at: ISO 8601 timestamp of last token update
        last_used: ISO 8601 timestamp of last API request (or None)
        needs_reauth: If True, refresh_token is invalid; requires re-authorization
    """

    account_id: str = Field(
        ...,
        min_length=1,
        max_length=ACCOUNT_ID_MAX_LENGTH,
        description="Unique identifier for this account",
    )
    email: str = Field(..., description="Google account email")
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token")
    token_type: str = Field(default="Bearer", description="Token type")
    scope: str = Field(..., description="Space-separated OAuth scopes")
    expiry_date: int = Field(
        ..., description="Token expiry in milliseconds since epoch"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 last update timestamp",
    )
    last_used: str | None = Field(
        default=None, description="ISO 8601 last used timestamp"
    )
    needs_reauth: bool = Field(
        default=False,
        description="If True, account requires re-authorization",
    )
    rate_limited_until: int | None = Field(
        default=None,
        description="Epoch ms until which this account is rate limited",
    )
    consecutive_rate_limits: int = Field(
        default=0,
        description="Number of consecutive times this account was rate limited",
    )
    project_id: str | None = Field(
        default=None,
        description="Cached Google Cloud project ID for Code Assist API",
    )

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        """Validate account_id matches allowed pattern."""
        if not _ACCOUNT_ID_REGEX.match(v):
            raise ValueError(
                f"account_id must match pattern: alphanumeric, hyphens, underscores; "
                f"max {ACCOUNT_ID_MAX_LENGTH} chars; got: {v!r}"
            )
        return v

    def is_expired(self, buffer_ms: int = 0) -> bool:
        """Check if access token is expired or will expire within buffer.

        Args:
            buffer_ms: Milliseconds before actual expiry to consider expired.
                       Default 0 means check actual expiry only.
                       Use 300_000 (5 minutes) for proactive refresh.

        Returns:
            True if token is expired or will expire within buffer.
        """
        current_time_ms = int(time.time() * 1000)
        return current_time_ms >= (self.expiry_date - buffer_ms)

    def is_rate_limited(self, now_ms: int | None = None) -> bool:
        """Check if account is currently rate limited."""
        if self.rate_limited_until is None:
            return False
        current_time_ms = now_ms or int(time.time() * 1000)
        return current_time_ms < self.rate_limited_until

    def rate_limit_remaining_ms(self, now_ms: int | None = None) -> int:
        """Return remaining rate limit window in milliseconds."""
        if self.rate_limited_until is None:
            return 0
        current_time_ms = now_ms or int(time.time() * 1000)
        return max(self.rate_limited_until - current_time_ms, 0)

    def to_credentials_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for API authentication.

        Returns format compatible with Google OAuth2 credentials:
        {
            "access_token": "...",
            "refresh_token": "...",
            "token_type": "Bearer",
            "expiry_date": 1737417600000,
            "project_id": "..." (if available)
        }
        """
        result = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expiry_date": self.expiry_date,
        }
        if self.project_id:
            result["project_id"] = self.project_id
        return result

    @property
    def status(self) -> Literal["valid", "expired", "needs_reauth"]:
        """Get account status for display.

        Returns:
            - "needs_reauth": Account requires re-authorization
            - "expired": Token is expired (may be refreshable)
            - "valid": Token is valid
        """
        if self.needs_reauth:
            return "needs_reauth"
        if self.is_expired():
            return "expired"
        return "valid"

    def with_updated_tokens(
        self,
        access_token: str,
        expiry_date: int,
        *,
        refresh_token: str | None = None,
    ) -> "StoredAccount":
        """Create new instance with updated tokens.

        Args:
            access_token: New access token
            expiry_date: New expiry timestamp in milliseconds
            refresh_token: New refresh token (optional, keeps existing if None)

        Returns:
            New StoredAccount instance with updated tokens and timestamps.
        """
        return self.model_copy(
            update={
                "access_token": access_token,
                "expiry_date": expiry_date,
                "refresh_token": refresh_token or self.refresh_token,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "needs_reauth": False,  # Clear flag on successful refresh
            }
        )

    def mark_used(self) -> "StoredAccount":
        """Create new instance with updated last_used timestamp and reset rate limit counter.

        Returns:
            New StoredAccount instance with current time as last_used.
        """
        return self.model_copy(
            update={
                "last_used": datetime.now(timezone.utc).isoformat(),
                "consecutive_rate_limits": 0,
            }
        )

    def mark_rate_limited(
        self,
        *,
        retry_after_seconds: float | None,
        default_window_seconds: float,
    ) -> "StoredAccount":
        """Create new instance marked as rate limited until a future time.

        Implements exponential backoff when retry_after_seconds is not specified.
        """
        import random

        now_ms = int(time.time() * 1000)

        # Increment consecutive rate limits
        new_consecutive = self.consecutive_rate_limits + 1

        if isinstance(retry_after_seconds, int | float) and retry_after_seconds > 0:
            # Use explicit retry-after if provided
            wait_seconds = float(retry_after_seconds)
        else:
            # Apply exponential backoff: default * (2 ^ (consecutive - 1))
            # 1st time: 30s * 1 = 30s
            # 2nd time: 30s * 2 = 60s
            # 3rd time: 30s * 4 = 120s
            # ...
            backoff_factor = 2 ** (new_consecutive - 1)
            base_wait = float(default_window_seconds) * backoff_factor

            # Add jitter (±10%)
            jitter = base_wait * 0.1
            wait_seconds = base_wait + random.uniform(-jitter, jitter)

            # Cap at 1 hour
            wait_seconds = min(wait_seconds, 3600.0)

        new_until = now_ms + int(wait_seconds * 1000)

        # Don't decrease rate limit time if already set further in future
        if self.rate_limited_until and self.rate_limited_until > new_until:
            new_until = self.rate_limited_until

        return self.model_copy(
            update={
                "rate_limited_until": new_until,
                "consecutive_rate_limits": new_consecutive,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )


class AccountSummary(BaseModel):
    """Summary information for account listing.

    Used for display in the management script's `list` command.
    Contains a subset of StoredAccount fields suitable for tabular display.
    """

    account_id: str
    email: str
    status: Literal["valid", "expired", "needs_reauth"]
    expiry_date: int
    last_used: str | None

    @classmethod
    def from_stored_account(cls, account: StoredAccount) -> "AccountSummary":
        """Create summary from full StoredAccount.

        Args:
            account: Full account credentials

        Returns:
            AccountSummary with display-relevant fields.
        """
        return cls(
            account_id=account.account_id,
            email=account.email,
            status=account.status,
            expiry_date=account.expiry_date,
            last_used=account.last_used,
        )


class GeminiOAuthAutoConfig(BaseModel):
    """Configuration for Gemini OAuth Auto-Connector."""

    accounts: list[str] | Literal["all"] = Field(
        default="all",
        description="List of account IDs to use, or 'all' for all registered accounts.",
    )
    refresh_buffer_seconds: int = Field(
        default=300,
        description="Seconds before expiry to proactively refresh the access token.",
    )
    selection_strategy: Literal[
        "round-robin",
        "random",
        "first-available",
        "session-affinity",
    ] = Field(
        default="session-affinity",
        description="Strategy for selecting which account to use for the next request.",
    )
    session_affinity_ttl_seconds: int = Field(
        default=86400,
        description="Seconds to keep session->account affinity mappings in memory.",
    )
    session_affinity_max_entries: int = Field(
        default=10000,
        description="Maximum number of session->account affinity mappings to retain.",
    )
    storage_path: str = Field(
        default="var/gemini_oauth_accounts",
        description="Path to directory where account credentials are stored.",
    )
