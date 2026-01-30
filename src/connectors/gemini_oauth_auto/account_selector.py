"""AccountSelectorService implementation.

Manages which account to use for API requests with round-robin rotation.
"""

import asyncio
import logging
import time

from src.connectors.gemini_oauth_auto.constants import (
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_REFRESH_BUFFER_MS,
)
from src.connectors.gemini_oauth_auto.errors import TokenRefreshError
from src.connectors.gemini_oauth_auto.interfaces import (
    IAccountSelector,
    ITokenRefresh,
    ITokenStorage,
)
from src.connectors.gemini_oauth_auto.models import StoredAccount

logger = logging.getLogger(__name__)


class AccountSelectorService(IAccountSelector):
    """Account selector service implementation.

    Provides round-robin account selection with quota-based failover.

    Features:
    - Round-robin rotation among valid accounts
    - Optional allowlist of account IDs
    - Skips accounts with needs_reauth=True
    - Proactive refresh for near-expiry accounts
    - Immediate rotation on quota exhaustion
    """

    def __init__(
        self,
        storage: ITokenStorage,
        refresh_service: ITokenRefresh,
        *,
        refresh_buffer_ms: int = DEFAULT_REFRESH_BUFFER_MS,
        allowed_account_ids: set[str] | None = None,
        selection_strategy: str = "round-robin",
    ) -> None:
        """Initialize account selector.

        Args:
            storage: Token storage service for account retrieval
            refresh_service: Token refresh service for proactive refresh
            refresh_buffer_ms: Token refresh buffer in milliseconds.
            allowed_account_ids: Optional allowlist of account IDs. If set, only these
                accounts will be used for selection.
            selection_strategy: Strategy for account selection (round-robin, random, first-available).
        """
        self._storage = storage
        self._refresh_service = refresh_service
        self._refresh_buffer_ms = refresh_buffer_ms
        self._allowed_account_ids = allowed_account_ids
        self._selection_strategy = selection_strategy

        self._current_account: StoredAccount | None = None
        self._accounts: list[StoredAccount] = []
        self._blocked_account_ids: set[str] = set()
        self._rotation_index: int = 0
        self._initialized: bool = False

    @property
    def rotation_index(self) -> int:
        """Current rotation index."""
        return self._rotation_index

    @rotation_index.setter
    def rotation_index(self, value: int) -> None:
        self._rotation_index = value

    @property
    def refresh_buffer_ms(self) -> int:
        """Refresh buffer in milliseconds."""
        return self._refresh_buffer_ms

    @refresh_buffer_ms.setter
    def refresh_buffer_ms(self, value: int) -> None:
        self._refresh_buffer_ms = value

    @property
    def allowed_account_ids(self) -> set[str] | None:
        """Set of allowed account IDs."""
        return self._allowed_account_ids

    @allowed_account_ids.setter
    def allowed_account_ids(self, value: set[str] | None) -> None:
        self._allowed_account_ids = value

    @property
    def selection_strategy(self) -> str:
        """Current selection strategy."""
        return self._selection_strategy

    @selection_strategy.setter
    def selection_strategy(self, value: str) -> None:
        self._selection_strategy = value

    @property
    def total_count(self) -> int:
        """Total count of loaded accounts."""
        return len(self._accounts)

    async def _ensure_accounts_loaded(self) -> None:
        """Load accounts from storage if not already loaded."""
        if not self._initialized:
            self._accounts = await self._storage.load_all_accounts()
            self._initialized = True
            logger.debug("Loaded %d accounts for selection", len(self._accounts))

    def _get_available_accounts(self) -> list[StoredAccount]:
        """Get list of accounts that don't need reauthorization.

        Applies allowlist filtering when `allowed_account_ids` is configured.
        Filters out accounts that are blocked in-memory until restart.

        Returns:
            List of accounts with needs_reauth=False and not blocked.
        """
        accounts = [
            acc
            for acc in self._accounts
            if not acc.needs_reauth and acc.account_id not in self._blocked_account_ids
        ]
        if self._allowed_account_ids is None:
            return accounts
        return [acc for acc in accounts if acc.account_id in self._allowed_account_ids]

    def _get_rate_limit_eligible_accounts(
        self, now_ms: int
    ) -> tuple[list[StoredAccount], list[StoredAccount]]:
        available = self._get_available_accounts()
        if not available:
            return [], []
        eligible = [acc for acc in available if not self._is_rate_limited(acc, now_ms)]
        return available, eligible

    def _is_rate_limited(self, account: StoredAccount, now_ms: int) -> bool:
        checker = getattr(account, "is_rate_limited", None)
        if callable(checker):
            try:
                result = checker(now_ms)
            except TypeError:
                result = checker()
            if isinstance(result, bool):
                return result
        rate_limited_until = getattr(account, "rate_limited_until", None)
        if isinstance(rate_limited_until, int):
            return now_ms < rate_limited_until
        return False

    def _get_next_wait_seconds(
        self, accounts: list[StoredAccount], now_ms: int
    ) -> float:
        if not accounts:
            return 0.0

        def _rate_limited_until(account: StoredAccount) -> int:
            value = getattr(account, "rate_limited_until", None)
            return value if isinstance(value, int) else now_ms

        soonest = min(
            accounts,
            key=_rate_limited_until,
        )
        rate_limited_until = _rate_limited_until(soonest)
        if rate_limited_until == now_ms:
            return 0.0
        return max((rate_limited_until - now_ms) / 1000.0, 0.0)

    async def get_next_account(self) -> StoredAccount | None:
        """Get next valid account based on selection strategy.

        Advances the rotation index and returns the next usable account.
        Skips accounts with needs_reauth=True.
        Triggers refresh for near-expiry accounts.

        Returns:
            Valid account, or None if no accounts available.
        """
        await self._ensure_accounts_loaded()

        while True:
            now_ms = int(time.time() * 1000)
            available, eligible = self._get_rate_limit_eligible_accounts(now_ms)
            if not available:
                logger.warning("No valid accounts available for selection")
                return None

            if not eligible:
                wait_seconds = self._get_next_wait_seconds(available, now_ms)
                if wait_seconds > 0:
                    soonest = min(
                        available,
                        key=lambda acc: getattr(acc, "rate_limited_until", None)
                        or now_ms,
                    )
                    logger.info(
                        "All accounts are rate limited; waiting %.2fs for account %s",
                        wait_seconds,
                        soonest.account_id,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                return None

            account = self._select_account_from_available(eligible)
            if not account:
                return None

            try:
                account = await self._refresh_service.refresh_if_needed(
                    account, buffer_ms=self._refresh_buffer_ms
                )
                self._update_account_in_list(account)
            except TokenRefreshError as e:
                if e.needs_reauth:
                    logger.warning(
                        "Account %s needs reauth, trying next account",
                        account.account_id,
                    )
                    account = account.model_copy(update={"needs_reauth": True})
                    self._update_account_in_list(account)
                    continue

                logger.warning(
                    "Failed to refresh account %s, using anyway: %s",
                    account.account_id,
                    e,
                )

            self._current_account = account
            logger.debug("Selected account: %s", account.account_id)
            return account

    def _select_account_from_available(
        self, available: list[StoredAccount]
    ) -> StoredAccount | None:
        if not available:
            return None

        if self._selection_strategy == "random":
            import random

            if len(available) > 1 and self._current_account:
                others = [
                    acc
                    for acc in available
                    if acc.account_id != self._current_account.account_id
                ]
                return random.choice(others)
            return random.choice(available)

        if self._selection_strategy == "first-available":
            return available[0]

        if self._rotation_index >= len(available):
            self._rotation_index = 0

        account = available[self._rotation_index]
        self._rotation_index = (self._rotation_index + 1) % len(available)
        return account

    async def mark_current_account_used(self) -> None:
        if not self._current_account:
            return

        updated = self._current_account.mark_used()
        self._current_account = updated
        self._update_account_in_list(updated)
        await self._storage.save_account(updated)
        logger.debug("Updated last_used for account: %s", updated.account_id)

    async def mark_current_account_rate_limited(
        self, retry_after_seconds: float | None
    ) -> None:
        if not self._current_account:
            return
        updated = self._current_account.mark_rate_limited(
            retry_after_seconds=retry_after_seconds,
            default_window_seconds=DEFAULT_RATE_LIMIT_SECONDS,
        )
        self._current_account = updated
        self._update_account_in_list(updated)
        await self._storage.save_account(updated)
        logger.info(
            "Marked account %s rate limited until %s",
            updated.account_id,
            updated.rate_limited_until,
        )

    def _update_account_in_list(self, updated: StoredAccount) -> None:
        """Update an account in our local list.

        Args:
            updated: Account with updated fields
        """
        for i, acc in enumerate(self._accounts):
            if acc.account_id == updated.account_id:
                self._accounts[i] = updated
                break

    def get_current_account(self) -> StoredAccount | None:
        """Get currently selected account without advancing."""
        return self._current_account

    async def rotate_on_quota(self) -> StoredAccount | None:
        """Rotate to next account due to quota exhaustion."""
        await self._ensure_accounts_loaded()

        available = self._get_available_accounts()
        if len(available) <= 1:
            logger.warning(
                "Cannot rotate: only %d account(s) available", len(available)
            )
            return None

        logger.debug(
            "Rotating away from account %s due to quota",
            self._current_account.account_id if self._current_account else "unknown",
        )

        # Get next account (get_next_account already advances index)
        return await self.get_next_account()

    def get_available_count(self) -> int:
        """Count of accounts not marked needs_reauth."""
        return len(self._get_available_accounts())

    def update_account(self, account: StoredAccount) -> None:
        """Update an account in the local cache and potentially current_account."""
        self._update_account_in_list(account)
        if (
            self._current_account
            and self._current_account.account_id == account.account_id
        ):
            self._current_account = account

    async def reload_accounts(self) -> None:
        """Force reload accounts from storage.

        Preserves rotation index and current account if possible.
        """
        self._accounts = await self._storage.load_all_accounts()
        # Don't reset rotation index - preserve it across reloads
        # Only reset if index is out of bounds
        if self._rotation_index >= len(self._accounts):
            self._rotation_index = 0
        # Update current account if it still exists in reloaded accounts
        if self._current_account:
            updated_current = next(
                (
                    acc
                    for acc in self._accounts
                    if acc.account_id == self._current_account.account_id
                ),
                None,
            )
            if updated_current:
                self._current_account = updated_current
            # If current account no longer exists, clear it (will be selected on next call)
        self._initialized = True
        logger.debug(
            "Reloaded %d accounts (rotation_index=%d)",
            len(self._accounts),
            self._rotation_index,
        )

    async def mark_current_account_blocked(self, reason: str) -> None:
        """Mark the currently selected account as blocked/unusable until restart.

        Args:
            reason: Reason why the account is being blocked.
        """
        if not self._current_account:
            return

        account_id = self._current_account.account_id
        if account_id not in self._blocked_account_ids:
            self._blocked_account_ids.add(account_id)
            logger.warning(
                "Account %s blocked until restart. Reason: %s",
                account_id,
                reason,
            )
            # Advancing index is not strictly necessary here as get_next_account
            # will skip this account next time, but clearing current ensures
            # we don't try to use it again for the same request if logic repeats.
            self._current_account = None
