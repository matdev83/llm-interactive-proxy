"""
Error classes for Gemini OAuth Auto-Connector.

Follows the project's error hierarchy:
- OAuthError: Script-only errors (not derived from LLMProxyError)
- TokenRefreshError, NoValidAccountsError: Runtime errors (extend LLMProxyError)
"""

from src.core.common.exceptions import LLMProxyError


class OAuthError(Exception):
    """Error during OAuth authorization flow.

    Used in the management script only. Not derived from LLMProxyError
    since OAuth flow happens outside the proxy runtime.
    """

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        """Initialize OAuth error.

        Args:
            message: Human-readable error description
            error_code: Optional OAuth error code from Google (e.g., 'access_denied')
        """
        super().__init__(message)
        self.error_code: str | None = error_code


class TokenRefreshError(LLMProxyError):
    """Error during automatic token refresh.

    Raised when the connector fails to refresh an expired token.
    The `needs_reauth` flag indicates whether the user must re-authorize
    the account via the management script.
    """

    def __init__(
        self,
        message: str,
        *,
        needs_reauth: bool = False,
        account_id: str | None = None,
    ) -> None:
        """Initialize token refresh error.

        Args:
            message: Human-readable error description
            needs_reauth: If True, refresh_token is invalid/revoked; user must re-auth
            account_id: The account that failed to refresh (for logging/rotation)
        """
        super().__init__(message)
        self.needs_reauth: bool = needs_reauth
        self.account_id: str | None = account_id


class NoValidAccountsError(LLMProxyError):
    """No valid accounts available for requests.

    Raised when the connector has no accounts that can be used:
    - All accounts are expired and refresh failed
    - All accounts are marked as needs_reauth
    - No accounts registered at all
    """

    def __init__(
        self,
        message: str = "No valid accounts available",
        *,
        total_accounts: int = 0,
        needs_reauth_count: int = 0,
    ) -> None:
        """Initialize no valid accounts error.

        Args:
            message: Human-readable error description
            total_accounts: Total number of registered accounts
            needs_reauth_count: Number of accounts requiring re-authorization
        """
        super().__init__(message)
        self.total_accounts: int = total_accounts
        self.needs_reauth_count: int = needs_reauth_count
        self.guidance: str = (
            "Run 'python scripts/manage_gemini_accounts.py add' to add an account, "
            "or 'python scripts/manage_gemini_accounts.py update <account-id>' "
            "to re-authorize an existing account."
        )
