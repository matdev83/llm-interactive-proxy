"""Account selection for Kiro OAuth auto-connector."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

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

    def _iter_candidates(self) -> Iterable[StoredAccount]:
        if not self._accounts:
            return []
        if self._selection_strategy == "round-robin":
            # Rotate starting index on each call
            start = self._current_idx % len(self._accounts)
            ordered = self._accounts[start:] + self._accounts[:start]
            return ordered
        return self._accounts

    async def get_next_account(self) -> StoredAccount:
        async with self._lock:
            if not self._accounts:
                raise NoValidAccountsError("No accounts found in storage")

            last_error: Exception | None = None
            for account in self._iter_candidates():
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
