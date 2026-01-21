"""
TokenRefreshService implementation.

Handles OAuth token refresh via HTTP POST to Google's token endpoint.
Provides proactive refresh (before expiry) and forced refresh (on 401).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from src.connectors.gemini_oauth_auto.constants import (
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    TOKEN_URL,
)
from src.connectors.gemini_oauth_auto.errors import TokenRefreshError
from src.connectors.gemini_oauth_auto.interfaces import ITokenRefresh, ITokenStorage
from src.connectors.gemini_oauth_auto.models import StoredAccount

logger = logging.getLogger(__name__)


class TokenRefreshService(ITokenRefresh):
    """Token refresh service implementation.

    Uses httpx.AsyncClient for HTTP-based token refresh with retry logic.

    Features:
    - Proactive refresh before expiry (configurable buffer)
    - Retry with exponential backoff for transient failures
    - Per-account locking to prevent concurrent refreshes
    - Double-check pattern for efficiency
    - Handles invalid_grant by setting needs_reauth flag
    """

    def __init__(
        self,
        storage: ITokenStorage,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        """Initialize token refresh service.

        Args:
            storage: Token storage service for persisting refreshed tokens
            http_client: httpx.AsyncClient for HTTP requests (shared from connector)
            max_retries: Maximum retry attempts for transient failures
            base_delay: Base delay in seconds for exponential backoff (1s, 2s, 4s)
        """
        self._storage = storage
        self._http_client = http_client
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, account_id: str) -> asyncio.Lock:
        """Get or create lock for account to prevent concurrent refresh.

        Args:
            account_id: Account identifier

        Returns:
            asyncio.Lock for this account
        """
        if account_id not in self._refresh_locks:
            self._refresh_locks[account_id] = asyncio.Lock()
        return self._refresh_locks[account_id]

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
        """
        if not account.is_expired(buffer_ms):
            logger.debug(
                "Token for account %s not near expiry, skipping refresh",
                account.account_id,
            )
            return account

        logger.debug(
            "Token for account %s within expiry buffer, refreshing",
            account.account_id,
        )
        return await self._do_refresh_with_retry(account)

    async def force_refresh(self, account: StoredAccount) -> StoredAccount:
        """Force immediate token refresh.

        Use after receiving 401 Unauthorized from the API.

        Args:
            account: Account to refresh

        Returns:
            Account with updated tokens.

        Raises:
            TokenRefreshError: If refresh fails.
        """
        logger.debug("Force refreshing token for account %s", account.account_id)
        return await self._do_refresh_with_retry(account)

    async def _do_refresh_with_retry(self, account: StoredAccount) -> StoredAccount:
        """Execute refresh with exponential backoff retry.

        Args:
            account: Account to refresh

        Returns:
            Account with updated tokens

        Raises:
            TokenRefreshError: On auth errors or after max retries
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                return await self._do_refresh(account)
            except TokenRefreshError:
                # Don't retry auth errors (invalid_grant, etc.)
                raise
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._base_delay * (2**attempt)  # 1s, 2s, 4s
                    logger.debug(
                        "Token refresh attempt %d/%d failed, retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._base_delay * (2**attempt)
                    logger.debug(
                        "Token refresh attempt %d/%d failed unexpectedly, "
                        "retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)

        error_msg = (
            f"Token refresh failed after {self._max_retries} attempts: {last_error}"
        )
        logger.error(error_msg)
        raise TokenRefreshError(error_msg, account_id=account.account_id)

    async def _do_refresh(self, account: StoredAccount) -> StoredAccount:
        """Execute single token refresh request with locking.

        Uses double-check pattern: after acquiring lock, checks if another
        coroutine already refreshed the token.

        Args:
            account: Account to refresh

        Returns:
            Account with updated tokens

        Raises:
            TokenRefreshError: On invalid_grant or other auth errors
            httpx.HTTPError: On network errors
        """
        async with self._get_lock(account.account_id):
            # Double-check: see if another coroutine already refreshed
            current = await self._storage.get_account(account.account_id)
            if current and not current.is_expired(buffer_ms=60_000):  # 1 min buffer
                logger.debug(
                    "Token for account %s already refreshed by another task",
                    account.account_id,
                )
                return current

            # Perform the refresh
            if self._http_client is None:
                # Create a temporary client if none provided
                async with httpx.AsyncClient() as client:
                    return await self._execute_refresh(account, client)
            else:
                return await self._execute_refresh(account, self._http_client)

    async def _execute_refresh(
        self, account: StoredAccount, client: httpx.AsyncClient
    ) -> StoredAccount:
        """Execute the HTTP token refresh request.

        Args:
            account: Account to refresh
            client: httpx client to use

        Returns:
            Account with updated tokens

        Raises:
            TokenRefreshError: On invalid_grant or other auth errors
            httpx.HTTPError: On network errors
        """
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET,
                "refresh_token": account.refresh_token,
                "grant_type": "refresh_token",
            },
        )

        # Handle error responses
        if response.status_code == 400:
            try:
                error_data = response.json()
                if error_data.get("error") == "invalid_grant":
                    # Refresh token revoked or expired - need re-authorization
                    logger.warning(
                        "Refresh token for account %s is invalid/revoked",
                        account.account_id,
                    )
                    # Update account with needs_reauth flag
                    updated_account = account.model_copy(update={"needs_reauth": True})
                    await self._storage.save_account(updated_account)
                    raise TokenRefreshError(
                        "Refresh token revoked or expired",
                        needs_reauth=True,
                        account_id=account.account_id,
                    )
            except TokenRefreshError:
                raise
            except Exception:
                pass  # Fall through to raise_for_status

        response.raise_for_status()

        # Parse successful response
        tokens = response.json()

        # Calculate new expiry
        expires_in = tokens.get("expires_in", 3600)  # Default 1 hour
        new_expiry = int(time.time() * 1000) + (expires_in * 1000)

        # Update account with new tokens
        updated_account = account.model_copy(
            update={
                "access_token": tokens["access_token"],
                "expiry_date": new_expiry,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "needs_reauth": False,  # Clear flag on successful refresh
            }
        )

        # Persist updated tokens
        await self._storage.save_account(updated_account)

        logger.debug(
            "Token refreshed for account %s, expires in %ds",
            account.account_id,
            expires_in,
        )

        return updated_account
