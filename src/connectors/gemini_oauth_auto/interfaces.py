"""
Service interfaces for Gemini OAuth Auto-Connector.

Defines abstract base classes for dependency injection and testing.
Follows project conventions: I* naming, ABC-based, async methods.
"""

from abc import ABC, abstractmethod

from src.connectors.gemini_oauth_auto.models import AccountSummary, StoredAccount


class ITokenStorage(ABC):
    """Interface for token storage operations.

    Manages persistence of OAuth credentials for multiple accounts.
    Storage location: var/gemini_oauth_accounts/{account_id}.json
    """

    @abstractmethod
    async def load_all_accounts(self) -> list[StoredAccount]:
        """Load all accounts from storage directory.

        Returns:
            List of valid accounts. Corrupted files are logged and skipped.

        Postcondition:
            - Returns list of valid accounts
            - Corrupted files logged at WARNING, not in result
            - Directory created if missing
        """
        ...

    @abstractmethod
    async def get_account(self, account_id: str) -> StoredAccount | None:
        """Get specific account by ID.

        Args:
            account_id: Account identifier to retrieve

        Returns:
            StoredAccount if found and valid, None otherwise.
        """
        ...

    @abstractmethod
    async def save_account(self, account: StoredAccount) -> None:
        """Save account credentials atomically.

        Args:
            account: Account to save

        Precondition:
            - account.account_id is valid (alphanumeric, hyphens, underscores)

        Postcondition:
            - File written atomically (temp + rename)
            - Restrictive permissions set (600 on POSIX)

        Raises:
            ValueError: If account_id is invalid
            IOError: If file cannot be written
        """
        ...

    @abstractmethod
    async def delete_account(self, account_id: str) -> bool:
        """Delete account credentials file.

        Args:
            account_id: Account identifier to delete

        Returns:
            True if deleted, False if account not found.
        """
        ...

    @abstractmethod
    async def list_accounts(self) -> list[AccountSummary]:
        """List all accounts with status information.

        Returns:
            List of AccountSummary for display purposes.
        """
        ...


class ITokenRefresh(ABC):
    """Interface for token refresh operations.

    Handles OAuth token refresh via HTTP POST to Google's token endpoint.
    Provides proactive refresh (before expiry) and forced refresh (on 401).
    """

    @abstractmethod
    async def refresh_if_needed(
        self, account: StoredAccount, buffer_ms: int = 300_000
    ) -> StoredAccount:
        """Refresh token if within buffer of expiry.

        Args:
            account: Account to potentially refresh
            buffer_ms: Milliseconds before expiry to trigger refresh.
                       Default 300_000 (5 minutes).

        Returns:
            Account with updated tokens, or unchanged if not needed.

        Raises:
            TokenRefreshError: If refresh fails.
                - If needs_reauth=True, refresh_token is invalid/revoked.
        """
        ...

    @abstractmethod
    async def force_refresh(self, account: StoredAccount) -> StoredAccount:
        """Force immediate token refresh.

        Use after receiving 401 Unauthorized from the API.

        Args:
            account: Account to refresh

        Returns:
            Account with updated tokens.

        Raises:
            TokenRefreshError: If refresh fails.
                - If needs_reauth=True, refresh_token is invalid/revoked.
        """
        ...


class IAccountSelector(ABC):
    """Interface for account selection operations.

    Manages which account to use for API requests.
    Supports round-robin rotation and quota-based failover.
    """

    @abstractmethod
    async def get_next_account(self) -> StoredAccount | None:
        """Get next valid account in rotation.

        Advances the rotation index and returns the next usable account.
        Skips accounts with needs_reauth=True.
        Triggers refresh for near-expiry accounts.

        Returns:
            Valid account, or None if no accounts available.

        Side effects:
            - Advances rotation index
            - May trigger token refresh for near-expiry accounts
        """
        ...

    @abstractmethod
    def get_current_account(self) -> StoredAccount | None:
        """Get currently selected account without advancing.

        Returns:
            Currently selected account, or None if not set.
        """
        ...

    @abstractmethod
    async def rotate_on_quota(self) -> StoredAccount | None:
        """Rotate to next account due to quota exhaustion.

        Called when HTTP 429 is received. Immediately advances to
        the next available account.

        Returns:
            Next available account, or None if all exhausted.
        """
        ...

    @abstractmethod
    def get_available_count(self) -> int:
        """Count of accounts not marked needs_reauth.

        Returns:
            Number of usable accounts.
        """
        ...
