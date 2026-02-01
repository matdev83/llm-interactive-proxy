"""Account selection for Kiro OAuth auto-connector."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from datetime import datetime, timezone

from src.connectors.kiro_oauth_auto.constants import DEFAULT_RATE_LIMIT_SECONDS


def _format_rate_limit_until(timestamp_ms: int | None) -> str:
    """Format rate limit timestamp for human-readable logging.

    Args:
        timestamp_ms: Unix timestamp in milliseconds when rate limit expires.

    Returns:
        Formatted string like "2026-02-01 15:22:09 (123s)" or "None".
    """
    if timestamp_ms is None:
        return "None"

    now_ms = int(time.time() * 1000)
    seconds_remaining = max((timestamp_ms - now_ms) / 1000.0, 0.0)

    # Convert milliseconds to seconds for datetime
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")

    return f"{formatted_time} ({seconds_remaining:.0f}s)"


from src.connectors.kiro_oauth_auto.errors import (
    NoValidAccountsError,
    TokenRefreshError,
)
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService

logger = logging.getLogger(__name__)


class AccountSelectorService:
    """Selects an account and refreshes it when needed."""

    def __init__(
        self,
        *,
        storage: TokenStorageService,
        refresh_service: TokenRefreshService,
        refresh_buffer_ms: int = 300_000,
        allowed_account_ids: set[str] | None = None,
        selection_strategy: str = "first-available",
    ) -> None:
        self._storage = storage
        self._refresh = refresh_service
        self._refresh_buffer_ms = refresh_buffer_ms
        self._allowed_ids = allowed_account_ids
        self._selection_strategy = selection_strategy
        self._lock = asyncio.Lock()
        self._accounts: list[StoredAccount] = []
        self._blocked_account_ids: set[str] = set()
        self._current_idx: int = 0

    async def reload_accounts(self) -> None:
        accounts = await self._storage.load_all_accounts()
        if self._allowed_ids is not None:
            accounts = [a for a in accounts if a.account_id in self._allowed_ids]
        self._accounts = sorted(accounts, key=lambda a: a.account_id)
        self._current_idx = 0

    def get_current_account(self) -> StoredAccount | None:
        if not self._accounts:
            return None
        idx = min(self._current_idx, len(self._accounts) - 1)
        return self._accounts[idx]

    def _iter_candidates(
        self, accounts: list[StoredAccount]
    ) -> Iterable[StoredAccount]:
        if not accounts:
            return []
        if self._selection_strategy == "round-robin":
            start = self._current_idx % len(accounts)
            return accounts[start:] + accounts[:start]
        return accounts

    def _next_rate_limit_wait(self, now_ms: int) -> tuple[float, str | None]:
        if not self._accounts:
            return 0.0, None
        soonest = min(self._accounts, key=lambda acc: acc.rate_limited_until or now_ms)
        if soonest.rate_limited_until is None:
            return 0.0, soonest.account_id
        wait_seconds = max((soonest.rate_limited_until - now_ms) / 1000.0, 0.0)
        return wait_seconds, soonest.account_id

    async def get_next_account(self) -> StoredAccount:
        while True:
            wait_seconds = 0.0
            wait_account_id: str | None = None
            async with self._lock:
                if not self._accounts:
                    raise NoValidAccountsError("No accounts found in storage")

                now_ms = int(time.time() * 1000)
                eligible = [
                    account
                    for account in self._accounts
                    if not account.is_rate_limited(now_ms)
                    and account.account_id not in self._blocked_account_ids
                ]

                if not eligible:
                    wait_seconds, wait_account_id = self._next_rate_limit_wait(now_ms)
                else:
                    last_error: Exception | None = None
                    for account in self._iter_candidates(eligible):
                        try:
                            if account.is_expired(buffer_ms=self._refresh_buffer_ms):
                                account = await self._refresh.refresh_account(account)
                                self._update_account(account)
                            self._set_current(account.account_id)
                            return account
                        except TokenRefreshError as exc:
                            last_error = exc
                            logger.warning(
                                "Failed to refresh account %s: %s",
                                account.account_id,
                                exc,
                                exc_info=True,
                            )
                            continue

                    raise NoValidAccountsError(
                        f"No valid accounts available{': ' + str(last_error) if last_error else ''}"
                    )

            if wait_seconds > 0:
                logger.info(
                    "All accounts are rate limited; waiting %.2fs for account %s",
                    wait_seconds,
                    wait_account_id or "unknown",
                )
                await asyncio.sleep(wait_seconds)
                continue
            break

        raise NoValidAccountsError("No accounts available after rate limit wait")

    async def mark_current_account_used(self) -> None:
        async with self._lock:
            account = self.get_current_account()
            if not account:
                return
            updated = account.mark_used()
            await self._storage.save_account(updated)
            self._update_account(updated)

            if self._selection_strategy == "round-robin":
                self._current_idx = (self._current_idx + 1) % max(
                    len(self._accounts), 1
                )

    async def mark_current_account_rate_limited(
        self, retry_after_seconds: float | None
    ) -> None:
        async with self._lock:
            account = self.get_current_account()
            if not account:
                return
            updated = account.mark_rate_limited(
                retry_after_seconds=retry_after_seconds,
                default_window_seconds=DEFAULT_RATE_LIMIT_SECONDS,
            )
            await self._storage.save_account(updated)
            self._update_account(updated)
            logger.info(
                "Marked account %s rate limited until %s",
                updated.account_id,
                _format_rate_limit_until(updated.rate_limited_until),
            )

    def _update_account(self, account: StoredAccount) -> None:
        for i, existing in enumerate(self._accounts):
            if existing.account_id == account.account_id:
                self._accounts[i] = account
                return
        self._accounts.append(account)

    def _set_current(self, account_id: str) -> None:
        for i, existing in enumerate(self._accounts):
            if existing.account_id == account_id:
                self._current_idx = i
                return

    async def mark_current_account_blocked(self, reason: str) -> None:
        """Mark the currently selected account as blocked/unusable until restart.

        Args:
            reason: Reason why the account is being blocked.
        """
        async with self._lock:
            account = self.get_current_account()
            if not account:
                return

            account_id = account.account_id
            if account_id not in self._blocked_account_ids:
                self._blocked_account_ids.add(account_id)
                logger.warning(
                    "Account %s blocked until restart. Reason: %s",
                    account_id,
                    reason,
                )
