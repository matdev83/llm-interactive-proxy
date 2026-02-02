"""AccountSelectorService implementation.

Manages which account to use for API requests with round-robin rotation.
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from src.core.interfaces.notification_service_interface import INotificationService


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
from src.connectors.gemini_oauth_auto.verification_url_extractor import (
    extract_first_url,
)

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

    # Global rotation state to coordinate across parallel requests/connector instances
    _global_rotation_indices: dict[str, int] = {}
    _rotation_lock = threading.Lock()

    def __init__(
        self,
        storage: ITokenStorage,
        refresh_service: ITokenRefresh,
        *,
        refresh_buffer_ms: int = DEFAULT_REFRESH_BUFFER_MS,
        allowed_account_ids: set[str] | None = None,
        selection_strategy: str = "round-robin",
        session_affinity_ttl_seconds: int = 86400,
        session_affinity_max_entries: int = 10000,
        session_affinity_max_wait_seconds: float | None = None,
        notification_service: INotificationService | None = None,
    ) -> None:
        """Initialize account selector.

        Args:
            storage: Token storage service for account retrieval
            refresh_service: Token refresh service for proactive refresh
            refresh_buffer_ms: Token refresh buffer in milliseconds.
            allowed_account_ids: Optional allowlist of account IDs. If set, only these
                accounts will be used for selection.
            selection_strategy: Strategy for account selection (round-robin, random, first-available).
            notification_service: Service for sending desktop notifications.
        """
        self._storage = storage
        self._refresh_service = refresh_service
        self._refresh_buffer_ms = refresh_buffer_ms
        self._allowed_account_ids = allowed_account_ids
        self._selection_strategy = selection_strategy
        self._session_affinity_ttl_seconds = session_affinity_ttl_seconds
        self._session_affinity_max_entries = session_affinity_max_entries
        self._session_affinity_max_wait_seconds = session_affinity_max_wait_seconds
        self._session_affinity: OrderedDict[str, tuple[str, float]] = OrderedDict()

        self._current_account: StoredAccount | None = None
        self._accounts: list[StoredAccount] = []
        self._blocked_account_ids: set[str] = set()
        self._initialized: bool = False
        self._notification_service = notification_service
        self._last_rate_limit_updates: dict[str, float] = {}  # account_id -> unix_timestamp

    @property
    def rotation_index(self) -> int:
        """Current rotation index."""
        storage_key = str(getattr(self._storage, "_storage_path", "default"))
        with self._rotation_lock:
            return self._global_rotation_indices.get(storage_key, 0)

    @rotation_index.setter
    def rotation_index(self, value: int) -> None:
        storage_key = str(getattr(self._storage, "_storage_path", "default"))
        with self._rotation_lock:
            self._global_rotation_indices[storage_key] = value

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
    def session_affinity_ttl_seconds(self) -> int:
        return self._session_affinity_ttl_seconds

    @session_affinity_ttl_seconds.setter
    def session_affinity_ttl_seconds(self, value: int) -> None:
        self._session_affinity_ttl_seconds = value

    @property
    def session_affinity_max_entries(self) -> int:
        return self._session_affinity_max_entries

    @session_affinity_max_entries.setter
    def session_affinity_max_entries(self, value: int) -> None:
        self._session_affinity_max_entries = value

    @property
    def session_affinity_max_wait_seconds(self) -> float | None:
        return self._session_affinity_max_wait_seconds

    @session_affinity_max_wait_seconds.setter
    def session_affinity_max_wait_seconds(self, value: float | None) -> None:
        self._session_affinity_max_wait_seconds = value

    @property
    def notification_service(self) -> INotificationService | None:
        """The notification service used by this selector."""
        return self._notification_service

    @notification_service.setter
    def notification_service(self, value: INotificationService | None) -> None:
        self._notification_service = value

    @property
    def notifications_enabled(self) -> bool:
        """Whether OS notifications are enabled."""
        if self._notification_service is None:
            return False
        return self._notification_service.is_enabled

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

    def _session_affinity_enabled(self) -> bool:
        return (
            self._selection_strategy == "session-affinity"
            and self._session_affinity_max_entries > 0
            and self._session_affinity_ttl_seconds > 0
        )

    def _clean_session_affinity_locked(self, now_s: float) -> None:
        if not self._session_affinity:
            return

        if not self._session_affinity_enabled():
            self._session_affinity.clear()
            return

        expire_before = now_s - float(self._session_affinity_ttl_seconds)
        while self._session_affinity:
            _, (_, last_used) = next(iter(self._session_affinity.items()))
            if last_used >= expire_before:
                break
            self._session_affinity.popitem(last=False)

        while len(self._session_affinity) > self._session_affinity_max_entries:
            self._session_affinity.popitem(last=False)

    def _record_session_affinity(
        self, session_id: str, account_id: str, now_s: float
    ) -> None:
        if not self._session_affinity_enabled():
            return
        if not session_id:
            return
        self._session_affinity[session_id] = (account_id, now_s)
        self._session_affinity.move_to_end(session_id)
        self._clean_session_affinity_locked(now_s)

    def _clear_session_affinity(self, session_id: str, reason: str) -> None:
        if session_id in self._session_affinity:
            self._session_affinity.pop(session_id, None)
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Session affinity cleared for session %s: %s",
                    session_id[:8],
                    reason,
                )

    def _get_session_affinity_account(
        self,
        session_id: str,
        available: list[StoredAccount],
        eligible: list[StoredAccount],
        now_s: float,
    ) -> StoredAccount | None:
        if not self._session_affinity_enabled():
            return None
        if not session_id:
            return None

        self._clean_session_affinity_locked(now_s)
        entry = self._session_affinity.get(session_id)
        if not entry:
            return None

        account_id, _ = entry
        available_by_id = {acc.account_id: acc for acc in available}
        eligible_ids = {acc.account_id for acc in eligible}

        candidate = available_by_id.get(account_id)
        if not candidate:
            self._clear_session_affinity(session_id, "account unavailable")
            return None

        if account_id not in eligible_ids:
            self._clear_session_affinity(session_id, "account not eligible")
            return None

        self._record_session_affinity(session_id, account_id, now_s)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Session affinity hit: session=%s account=%s",
                session_id[:8],
                account_id,
            )
        return candidate

    def _get_session_affinity_wait_seconds(
        self, session_id: str, available: list[StoredAccount], now_ms: int
    ) -> float | None:
        if not self._session_affinity_enabled():
            return None
        if not session_id:
            return None
        max_wait = self._session_affinity_max_wait_seconds
        if max_wait is None or max_wait <= 0:
            return None

        entry = self._session_affinity.get(session_id)
        if not entry:
            return None

        account_id, _ = entry
        candidate = next(
            (acc for acc in available if acc.account_id == account_id), None
        )
        if not candidate:
            return None

        rate_limited_until = getattr(candidate, "rate_limited_until", None)
        if not isinstance(rate_limited_until, int):
            return None

        wait_seconds = max((rate_limited_until - now_ms) / 1000.0, 0.0)
        if wait_seconds <= 0:
            return None

        return wait_seconds if wait_seconds <= max_wait else None

    async def get_next_account(
        self,
        *,
        session_id: str | None = None,
        ignore_session_affinity: bool = False,
    ) -> StoredAccount | None:
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
            now_s = float(now_ms) / 1000.0
            available, eligible = self._get_rate_limit_eligible_accounts(now_ms)
            if not available:
                logger.warning("No valid accounts available for selection")
                return None

            if not ignore_session_affinity:
                wait_seconds = self._get_session_affinity_wait_seconds(
                    session_id or "",
                    available,
                    now_ms,
                )
                if wait_seconds is not None:
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Session affinity waiting %.1fs for rate-limited account (session=%s)",
                            wait_seconds,
                            (session_id or "")[:8] or "none",
                        )
                    await asyncio.sleep(wait_seconds)
                    continue

            if not eligible:
                wait_seconds = self._get_next_wait_seconds(available, now_ms)
                # Respect max wait time if configured
                max_wait = self._session_affinity_max_wait_seconds or 30.0
                if 0 < wait_seconds <= max_wait:
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

                logger.warning(
                    "All accounts are rate limited and wait time (%.2fs) exceeds limit (%.2fs)",
                    wait_seconds,
                    max_wait,
                )
                return None

            affinity_hit = False
            account: StoredAccount | None = None
            if not ignore_session_affinity:
                account = self._get_session_affinity_account(
                    session_id or "",
                    available,
                    eligible,
                    now_s,
                )
                affinity_hit = account is not None

            if not account:
                fallback_strategy = (
                    "round-robin"
                    if self._selection_strategy == "session-affinity"
                    else self._selection_strategy
                )
                account = self._select_account_from_available(
                    eligible, strategy=fallback_strategy
                )
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
                    if session_id:
                        self._clear_session_affinity(session_id, "needs reauth")
                    continue

                logger.warning(
                    "Failed to refresh account %s, using anyway: %s",
                    account.account_id,
                    e,
                )

            self._current_account = account
            if session_id and self._session_affinity_enabled():
                previous = self._session_affinity.get(session_id)
                previous_account_id = previous[0] if previous else None
                self._record_session_affinity(session_id, account.account_id, now_s)
                if previous_account_id != account.account_id and logger.isEnabledFor(
                    logging.INFO
                ):
                    label = (
                        "Session affinity rotated"
                        if ignore_session_affinity
                        else "Session affinity assigned"
                    )
                    logger.info(
                        "%s: session=%s account=%s",
                        label,
                        session_id[:8],
                        account.account_id,
                    )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Selected account: %s (affinity=%s)",
                    account.account_id,
                    affinity_hit,
                )
            return account

    def _select_account_from_available(
        self, available: list[StoredAccount], *, strategy: str | None = None
    ) -> StoredAccount | None:
        if not available:
            return None

        selection_strategy = strategy or self._selection_strategy
        if selection_strategy == "random":
            import random

            if len(available) > 1 and self._current_account:
                others = [
                    acc
                    for acc in available
                    if acc.account_id != self._current_account.account_id
                ]
                return random.choice(others)
            return random.choice(available)

        if selection_strategy == "first-available":
            return available[0]

        # Use shared rotation state
        storage_key = str(getattr(self._storage, "_storage_path", "default"))
        with self._rotation_lock:
            idx = self._global_rotation_indices.get(storage_key, 0)
            if idx >= len(available):
                idx = 0

            account = available[idx]
            self._global_rotation_indices[storage_key] = (idx + 1) % len(available)
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

        # Logic amplification protection: Avoid duplicate marking of the same account
        # within a short window (e.g. 2s) when nested generators unwind.
        account_id = self._current_account.account_id
        now = time.time()
        last_update = self._last_rate_limit_updates.get(account_id, 0.0)
        if now - last_update < 2.0:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping redundant rate limit marking for account %s (cooldown active)",
                    account_id,
                )
            return

        self._last_rate_limit_updates[account_id] = now
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
            _format_rate_limit_until(updated.rate_limited_until),
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

    async def rotate_on_quota(
        self, *, session_id: str | None = None, retry_after_seconds: float | None = None
    ) -> StoredAccount | None:
        """Rotate to next account due to quota exhaustion."""
        await self._ensure_accounts_loaded()

        if self._current_account:
            await self.mark_current_account_rate_limited(retry_after_seconds)

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
        return await self.get_next_account(
            session_id=session_id,
            ignore_session_affinity=True,
        )

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

        # Ensure rotation index is within bounds of newly loaded accounts
        if self._accounts and self.rotation_index >= len(self._accounts):
            self.rotation_index = 0

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
            self.rotation_index,
        )

    async def _send_block_notification(self, account: StoredAccount, reason: str) -> None:
        """Send OS notification when account gets blocked.

        Args:
            account: The account that was blocked.
            reason: Reason why the account is being blocked.
        """
        if self._notification_service is None:
            return

        # Count other available accounts (excluding the one just blocked)
        available_accounts = self._get_available_accounts()
        other_accounts_count = len(available_accounts)

        verification_url = extract_first_url(reason)
        identity_str = account.email or account.account_id

        message = f"Gemini OAuth account '{identity_str}' requires additional verification."
        if verification_url:
            message += f"\n\nVerify: {verification_url}"

        if other_accounts_count > 0:
            message += f"\n\nOther available accounts: {other_accounts_count}"
        else:
            message += "\n\nNo other accounts available!"

        try:
            await self._notification_service.send_notification(
                title="Gemini OAuth account needs verification",
                message=message,
                url=verification_url,
                url_label="Verify account",
            )
        except Exception as e:
            logger.debug("Failed to send block notification: %s", e)

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
            # Send OS notification (only once per blocking event)
            await self._send_block_notification(self._current_account, reason)
            if self._session_affinity:
                sessions_to_clear = [
                    session
                    for session, (acc_id, _) in self._session_affinity.items()
                    if acc_id == account_id
                ]
                for session in sessions_to_clear:
                    self._session_affinity.pop(session, None)
                if sessions_to_clear and logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Cleared %d session affinity mapping(s) for account %s",
                        len(sessions_to_clear),
                        account_id,
                    )
            # Advancing index is not strictly necessary here as get_next_account
            # will skip this account next time, but clearing current ensures
            # we don't try to use it again for the same request if logic repeats.
            self._current_account = None
