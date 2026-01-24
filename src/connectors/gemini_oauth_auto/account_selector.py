"""AccountSelectorService implementation.

Manages which account to use for API requests with round-robin rotation.
"""

import logging

from src.connectors.gemini_oauth_auto.constants import DEFAULT_REFRESH_BUFFER_MS
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
    ) -> None:
        """Initialize account selector.

        Args:
            storage: Token storage service for account retrieval
            refresh_service: Token refresh service for proactive refresh
            refresh_buffer_ms: Token refresh buffer in milliseconds.
            allowed_account_ids: Optional allowlist of account IDs. If set, only these
                accounts will be used for selection.
        """
        self._storage = storage
        self._refresh_service = refresh_service
        self._refresh_buffer_ms = refresh_buffer_ms
        self._allowed_account_ids = allowed_account_ids

        self._current_account: StoredAccount | None = None
        self._accounts: list[StoredAccount] = []
        self._rotation_index: int = 0
        self._initialized: bool = False

    async def _ensure_accounts_loaded(self) -> None:
        """Load accounts from storage if not already loaded."""
        if not self._initialized:
            self._accounts = await self._storage.load_all_accounts()
            self._initialized = True
            logger.debug("Loaded %d accounts for selection", len(self._accounts))

    def _get_available_accounts(self) -> list[StoredAccount]:
        """Get list of accounts that don't need reauthorization.

        Applies allowlist filtering when `allowed_account_ids` is configured.

        Returns:
            List of accounts with needs_reauth=False
        """
        accounts = [acc for acc in self._accounts if not acc.needs_reauth]
        if self._allowed_account_ids is None:
            return accounts
        return [acc for acc in accounts if acc.account_id in self._allowed_account_ids]

    async def get_next_account(self) -> StoredAccount | None:
        """Get next valid account in rotation.

        Advances the rotation index and returns the next usable account.
        Skips accounts with needs_reauth=True.
        Triggers refresh for near-expiry accounts.

        Returns:
            Valid account, or None if no accounts available.
        """
        await self._ensure_accounts_loaded()

        available = self._get_available_accounts()
        if not available:
            logger.warning("No valid accounts available for selection")
            return None

        # Round-robin selection
        if self._rotation_index >= len(available):
            self._rotation_index = 0

        account = available[self._rotation_index]
        self._rotation_index = (self._rotation_index + 1) % len(available)

        # Try to refresh if near expiry
        try:
            account = await self._refresh_service.refresh_if_needed(
                account, buffer_ms=self._refresh_buffer_ms
            )
            # Update account in our list with refreshed version
            self._update_account_in_list(account)
        except TokenRefreshError as e:
            if e.needs_reauth:
                # Account needs reauthorization, mark it and try next
                logger.warning(
                    "Account %s needs reauth, trying next account",
                    account.account_id,
                )
                # Update our local list with needs_reauth flag
                account = account.model_copy(update={"needs_reauth": True})
                self._update_account_in_list(account)
                # Recursively try next account
                return await self.get_next_account()

            # For other refresh errors, still return the account (it might work).
            logger.warning(
                "Failed to refresh account %s, using anyway: %s",
                account.account_id,
                e,
            )

        self._current_account = account
        logger.debug("Selected account: %s", account.account_id)
        return account

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
            logger.warning("Cannot rotate: only %d account(s) available", len(available))
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

    async def reload_accounts(self) -> None:
        """Force reload accounts from storage."""
        self._accounts = await self._storage.load_all_accounts()
        self._rotation_index = 0
        self._current_account = None
        self._initialized = True
        logger.debug("Reloaded %d accounts", len(self._accounts))
