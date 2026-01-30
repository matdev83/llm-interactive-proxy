"""Pydantic models for Kiro OAuth Auto-Connector."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.connectors.kiro_oauth_auto.constants import (
    ACCOUNT_ID_MAX_LENGTH,
    ACCOUNT_ID_PATTERN,
    DEFAULT_REGION,
)

_ACCOUNT_ID_REGEX = re.compile(ACCOUNT_ID_PATTERN)


class StoredAccount(BaseModel):
    """Stored OAuth credentials for Kiro inference APIs."""

    account_id: str = Field(
        ...,
        min_length=1,
        max_length=ACCOUNT_ID_MAX_LENGTH,
        description="Unique identifier for this account",
    )
    auth_method: Literal["builderid", "iamsso", "social"] = Field(
        default="builderid",
        description="Authentication method used to obtain tokens",
    )
    region: str = Field(default=DEFAULT_REGION, description="AWS region for OIDC")

    access_token: str = Field(..., description="OIDC access token")
    refresh_token: str = Field(..., description="OIDC refresh token")
    client_id: str = Field(..., description="OIDC client id")
    client_secret: str = Field(..., description="OIDC client secret")

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
    rate_limited_until: int | None = Field(
        default=None,
        description="Epoch ms until which this account is rate limited",
    )

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        if not _ACCOUNT_ID_REGEX.match(v):
            raise ValueError(
                f"account_id must match pattern (max {ACCOUNT_ID_MAX_LENGTH} chars): {v!r}"
            )
        return v

    def is_expired(self, buffer_ms: int = 0) -> bool:
        now_ms = int(time.time() * 1000)
        return now_ms >= (self.expiry_date - buffer_ms)

    def mark_used(self) -> StoredAccount:
        return self.model_copy(
            update={"last_used": datetime.now(timezone.utc).isoformat()}
        )

    def is_rate_limited(self, now_ms: int | None = None) -> bool:
        if self.rate_limited_until is None:
            return False
        current_time_ms = now_ms or int(time.time() * 1000)
        return current_time_ms < self.rate_limited_until

    def rate_limit_remaining_ms(self, now_ms: int | None = None) -> int:
        if self.rate_limited_until is None:
            return 0
        current_time_ms = now_ms or int(time.time() * 1000)
        return max(self.rate_limited_until - current_time_ms, 0)

    def with_updated_tokens(
        self,
        *,
        access_token: str,
        expiry_date: int,
        refresh_token: str | None = None,
    ) -> StoredAccount:
        return self.model_copy(
            update={
                "access_token": access_token,
                "expiry_date": expiry_date,
                "refresh_token": refresh_token or self.refresh_token,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def mark_rate_limited(
        self,
        *,
        retry_after_seconds: float | None,
        default_window_seconds: float,
    ) -> StoredAccount:
        now_ms = int(time.time() * 1000)
        wait_seconds = (
            float(retry_after_seconds)
            if isinstance(retry_after_seconds, int | float) and retry_after_seconds > 0
            else float(default_window_seconds)
        )
        new_until = now_ms + int(wait_seconds * 1000)
        if self.rate_limited_until and self.rate_limited_until > new_until:
            new_until = self.rate_limited_until
        return self.model_copy(
            update={
                "rate_limited_until": new_until,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )


class AccountSummary(BaseModel):
    """Summary for listing accounts."""

    account_id: str
    auth_method: Literal["builderid", "iamsso", "social"]
    region: str
    status: Literal["valid", "expired"]
    expiry_date: int
    last_used: str | None

    @classmethod
    def from_stored_account(cls, account: StoredAccount) -> AccountSummary:
        return cls(
            account_id=account.account_id,
            auth_method=account.auth_method,
            region=account.region,
            status="expired" if account.is_expired() else "valid",
            expiry_date=account.expiry_date,
            last_used=account.last_used,
        )


class KiroOAuthAutoConfig(BaseModel):
    """Configuration for Kiro OAuth Auto-Connector."""

    accounts: list[str] | Literal["all"] = Field(
        default="all",
        description="List of account IDs to use, or 'all'.",
    )
    refresh_buffer_seconds: int = Field(
        default=300,
        description="Seconds before expiry to proactively refresh the access token.",
    )
    selection_strategy: Literal["first-available", "round-robin"] = Field(
        default="first-available",
        description="Account selection strategy.",
    )
    storage_path: str = Field(
        default="var/kiro_oauth_accounts",
        description="Path to directory where account credentials are stored.",
    )
    preferred_endpoint: Literal["codewhisperer", "amazonq"] | None = Field(
        default="codewhisperer",
        description="Preferred inference endpoint; will fall back on quota errors.",
    )
    origin: Literal["AI_EDITOR", "CLI"] = Field(
        default="AI_EDITOR",
        description="Request origin header value used by Kiro APIs.",
    )
