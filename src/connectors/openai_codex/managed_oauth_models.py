"""Data models for OpenAI Codex managed OAuth accounts."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.connectors.openai_codex.managed_oauth_jwt import extract_expiry_ms_from_token

ACCOUNT_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
_ACCOUNT_ID_REGEX = re.compile(ACCOUNT_ID_PATTERN)

SelectionStrategy = Literal[
    "round-robin",
    "random",
    "first-available",
    "session-affinity",
]


class ManagedOAuthAccount(BaseModel):
    """Stored OpenAI OAuth account used by the `openai-codex` connector."""

    account_id: str = Field(..., min_length=1, max_length=64)
    email: str | None = None
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    scope: str = "openid profile email"
    expiry_date: int | None = Field(
        default=None,
        description="Epoch timestamp in milliseconds when access token expires.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_used: str | None = None
    needs_reauth: bool = False
    chatgpt_account_id: str | None = None
    rate_limited_until: int | None = None
    consecutive_auth_failures: int = 0
    last_codex_quota_headers: dict[str, str] | None = Field(
        default=None,
        description="Last x-codex-* response headers observed for this account (proxy runtime).",
    )
    last_codex_quota_observed_at: str | None = Field(
        default=None,
        description="ISO UTC timestamp when last_codex_quota_headers was captured.",
    )
    last_codex_usage_limit: dict[str, Any] | None = Field(
        default=None,
        description="Last Codex usage_limit_reached payload subset plus observed_at.",
    )

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: str) -> str:
        if not _ACCOUNT_ID_REGEX.match(value):
            raise ValueError(
                "account_id must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ pattern"
            )
        return value

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("expiry_date must be positive when provided")
        return value

    def get_effective_expiry_ms(self) -> int | None:
        """Return expiry from explicit field or derive from token claims."""
        if self.expiry_date is not None:
            return self.expiry_date
        return extract_expiry_ms_from_token(self.access_token)

    def is_expired(self, buffer_ms: int = 0) -> bool:
        """Check whether token is expired or close to expiry."""
        expiry_ms = self.get_effective_expiry_ms()
        if expiry_ms is None:
            return False
        now_ms = int(time.time() * 1000)
        return now_ms >= (expiry_ms - buffer_ms)

    def is_rate_limited(self, now_ms: int | None = None) -> bool:
        """Check whether account is under rate-limit cooldown."""
        if self.rate_limited_until is None:
            return False
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        return current < self.rate_limited_until

    @property
    def status(self) -> Literal["valid", "expired", "needs_reauth", "rate_limited"]:
        if self.needs_reauth:
            return "needs_reauth"
        if self.is_rate_limited():
            return "rate_limited"
        if self.is_expired():
            return "expired"
        return "valid"

    def with_updated_tokens(
        self,
        *,
        access_token: str,
        refresh_token: str | None = None,
        expiry_date: int | None = None,
        email: str | None = None,
        chatgpt_account_id: str | None = None,
        scope: str | None = None,
        token_type: str | None = None,
    ) -> ManagedOAuthAccount:
        """Return account copy with refreshed token fields."""
        return self.model_copy(
            update={
                "access_token": access_token,
                "refresh_token": refresh_token or self.refresh_token,
                "expiry_date": expiry_date,
                "email": email or self.email,
                "chatgpt_account_id": chatgpt_account_id or self.chatgpt_account_id,
                "scope": scope or self.scope,
                "token_type": token_type or self.token_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "needs_reauth": False,
                "consecutive_auth_failures": 0,
            }
        )

    def mark_used(self) -> ManagedOAuthAccount:
        """Return account copy with updated last_used timestamp."""
        return self.model_copy(
            update={
                "last_used": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def mark_needs_reauth(self) -> ManagedOAuthAccount:
        """Return account copy marked as requiring re-authorization."""
        return self.model_copy(
            update={
                "needs_reauth": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def mark_rate_limited(
        self,
        retry_after_seconds: float | None,
        *,
        local_cooldown_cap_seconds: float | None = None,
    ) -> ManagedOAuthAccount:
        """Return account copy with temporary rate-limit cooldown."""
        wait_seconds = (
            retry_after_seconds
            if retry_after_seconds and retry_after_seconds > 0
            else 30.0
        )
        if (
            local_cooldown_cap_seconds is not None
            and float(local_cooldown_cap_seconds) > 0
        ):
            wait_seconds = min(wait_seconds, float(local_cooldown_cap_seconds))
        wait_ms = int(wait_seconds * 1000)
        now_ms = int(time.time() * 1000)
        return self.model_copy(
            update={
                "rate_limited_until": now_ms + wait_ms,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def mark_auth_failure(self) -> ManagedOAuthAccount:
        """Return account copy with incremented auth failure counter."""
        return self.model_copy(
            update={
                "consecutive_auth_failures": self.consecutive_auth_failures + 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )


class ManagedOAuthAccountSummary(BaseModel):
    """Display-friendly summary for account listing commands."""

    account_id: str
    email: str | None
    status: Literal["valid", "expired", "needs_reauth", "rate_limited"]
    expiry_date: int | None
    last_used: str | None

    @classmethod
    def from_account(cls, account: ManagedOAuthAccount) -> ManagedOAuthAccountSummary:
        return cls(
            account_id=account.account_id,
            email=account.email,
            status=account.status,
            expiry_date=account.get_effective_expiry_ms(),
            last_used=account.last_used,
        )


class ManagedOAuthConfig(BaseModel):
    """Runtime configuration for managed OpenAI Codex OAuth."""

    enabled: bool = True
    storage_path: str
    accounts: list[str] | Literal["all"] = "all"
    selection_strategy: SelectionStrategy = "round-robin"
    refresh_buffer_seconds: int = 300
    session_affinity_ttl_seconds: int = 86400
    session_affinity_max_entries: int = 10000
    allow_legacy_fallback: bool = True
    #: Max seconds to sleep in :meth:`ManagedOAuthAccountSelector.get_next_account`
    #: while waiting for a rate-limited account to become eligible again.
    max_rate_limit_wait_seconds: float = 300.0
    #: Caps how long an account stays locally ``rate_limited`` for rotation purposes
    #: when upstream sends very large ``resets_in_seconds``. Full upstream metadata is
    #: still stored on ``last_codex_usage_limit``.
    rate_limit_local_cooldown_cap_seconds: float = 1800.0
    #: Max idle polls (sleeps) while all accounts are rate-limited before giving up.
    max_rate_limit_idle_polls: int = 48

    @classmethod
    def from_mapping(
        cls,
        source: dict[str, Any],
        *,
        default_storage_path: str,
    ) -> ManagedOAuthConfig:
        """Build config model from normalized settings mapping."""
        payload = dict(source)
        payload.setdefault("storage_path", default_storage_path)
        return cls.model_validate(payload)
