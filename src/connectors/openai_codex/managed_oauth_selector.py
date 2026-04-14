"""Account selection and rotation for OpenAI Codex managed OAuth."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_refresh import (
    ManagedOAuthRefreshError,
    ManagedOAuthRefreshService,
)
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService

logger = logging.getLogger(__name__)


class ManagedOAuthAccountSelector:
    """Selects accounts and rotates on auth/quota failures."""

    _global_rotation_indices: dict[str, int] = {}
    _rotation_locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        storage: ManagedOAuthStorageService,
        refresh_service: ManagedOAuthRefreshService,
        *,
        refresh_buffer_ms: int = 300_000,
        allowed_account_ids: set[str] | None = None,
        selection_strategy: str = "round-robin",
        session_affinity_ttl_seconds: int = 86_400,
        session_affinity_max_entries: int = 10_000,
        max_rate_limit_wait_seconds: float = 300.0,
        rate_limit_local_cooldown_cap_seconds: float = 1800.0,
        max_rate_limit_idle_polls: int = 48,
    ) -> None:
        self._storage = storage
        self._refresh_service = refresh_service
        self._refresh_buffer_ms = max(0, int(refresh_buffer_ms))
        self._allowed_account_ids = allowed_account_ids
        self._selection_strategy = selection_strategy
        self._session_affinity_ttl_seconds = max(0, int(session_affinity_ttl_seconds))
        self._session_affinity_max_entries = max(0, int(session_affinity_max_entries))
        self._max_rate_limit_wait_seconds = max(0.0, float(max_rate_limit_wait_seconds))
        self._rate_limit_local_cooldown_cap_seconds = max(
            0.0, float(rate_limit_local_cooldown_cap_seconds)
        )
        self._max_rate_limit_idle_polls = max(1, int(max_rate_limit_idle_polls))
        self._session_affinity: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._accounts: list[ManagedOAuthAccount] = []
        self._current_account: ManagedOAuthAccount | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    def _storage_key(self) -> str:
        return str(self._storage.storage_path.resolve())

    @classmethod
    def _rotation_lock(cls, storage_key: str) -> asyncio.Lock:
        lock = cls._rotation_locks.get(storage_key)
        if lock is None:
            lock = asyncio.Lock()
            cls._rotation_locks[storage_key] = lock
        return lock

    async def reload_accounts(self) -> None:
        async with self._lock:
            self._accounts = await self._storage.load_all_accounts()
            self._initialized = True
            if self._accounts:
                storage_key = self._storage_key()
                index = self._global_rotation_indices.get(storage_key, 0)
                if index >= len(self._accounts):
                    self._global_rotation_indices[storage_key] = 0
            if self._current_account is not None:
                current_id = self._current_account.account_id
                self._current_account = next(
                    (acc for acc in self._accounts if acc.account_id == current_id),
                    None,
                )

    async def _ensure_accounts_loaded(self) -> None:
        if self._initialized:
            return
        await self.reload_accounts()

    def _session_affinity_enabled(self) -> bool:
        return (
            self._selection_strategy == "session-affinity"
            and self._session_affinity_max_entries > 0
            and self._session_affinity_ttl_seconds > 0
        )

    def _clean_affinity(self, now_s: float) -> None:
        if not self._session_affinity:
            return
        if not self._session_affinity_enabled():
            self._session_affinity.clear()
            return
        expire_before = now_s - float(self._session_affinity_ttl_seconds)
        while self._session_affinity:
            _, (_, last_seen_s) = next(iter(self._session_affinity.items()))
            if last_seen_s >= expire_before:
                break
            self._session_affinity.popitem(last=False)
        while len(self._session_affinity) > self._session_affinity_max_entries:
            self._session_affinity.popitem(last=False)

    def _record_affinity(self, session_id: str, account_id: str, now_s: float) -> None:
        if not self._session_affinity_enabled() or not session_id:
            return
        self._session_affinity[session_id] = (account_id, now_s)
        self._session_affinity.move_to_end(session_id)
        self._clean_affinity(now_s)

    def _clear_affinity(self, session_id: str) -> None:
        if session_id:
            self._session_affinity.pop(session_id, None)

    def _available_accounts(
        self, now_ms: int
    ) -> tuple[list[ManagedOAuthAccount], list[ManagedOAuthAccount]]:
        available: list[ManagedOAuthAccount] = []
        for account in self._accounts:
            if self._allowed_account_ids is not None and (
                account.account_id not in self._allowed_account_ids
            ):
                continue
            if account.needs_reauth:
                continue
            available.append(account)
        eligible = [
            account for account in available if not account.is_rate_limited(now_ms)
        ]
        return available, eligible

    async def list_eligible_account_ids(self) -> list[str]:
        """Return currently eligible account IDs after reload/refresh gating."""
        await self._ensure_accounts_loaded()
        now_ms = int(time.time() * 1000)
        _, eligible = self._available_accounts(now_ms)
        return [account.account_id for account in eligible]

    async def count_available_managed_accounts(self) -> int:
        """Count managed accounts that can participate in rotation (not needs_reauth)."""
        await self._ensure_accounts_loaded()
        now_ms = int(time.time() * 1000)
        available, _ = self._available_accounts(now_ms)
        return len(available)

    def count_eligible_accounts_excluding(self, account_id: str) -> int:
        """Count accounts that can serve traffic, excluding ``account_id``.

        Uses the same eligibility rules as :meth:`get_next_account`: allowlist,
        not ``needs_reauth``, and not currently rate-limited. Intended for
        notifications when the excluded account is about to be marked limited.
        """
        now_ms = int(time.time() * 1000)
        _, eligible = self._available_accounts(now_ms)
        return sum(1 for a in eligible if a.account_id != account_id)

    def _select_by_strategy(
        self,
        eligible: list[ManagedOAuthAccount],
    ) -> ManagedOAuthAccount | None:
        if not eligible:
            return None
        strategy = (
            "round-robin"
            if self._selection_strategy == "session-affinity"
            else self._selection_strategy
        )
        if strategy == "first-available":
            return eligible[0]
        if strategy == "random":
            if len(eligible) > 1 and self._current_account is not None:
                others = [
                    account
                    for account in eligible
                    if account.account_id != self._current_account.account_id
                ]
                if others:
                    return random.choice(others)
            return random.choice(eligible)
        # default: round-robin
        storage_key = self._storage_key()
        index = self._global_rotation_indices.get(storage_key, 0)
        if index >= len(eligible):
            index = 0
        selected = eligible[index]
        self._global_rotation_indices[storage_key] = (index + 1) % len(eligible)
        return selected

    async def _select_round_robin_with_lock(
        self,
        eligible: list[ManagedOAuthAccount],
    ) -> ManagedOAuthAccount | None:
        if self._selection_strategy not in {"round-robin", "session-affinity"}:
            return self._select_by_strategy(eligible)
        if not eligible:
            return None
        storage_key = self._storage_key()
        async with self._rotation_lock(storage_key):
            return self._select_by_strategy(eligible)

    def _get_affinity_candidate(
        self,
        session_id: str,
        available: list[ManagedOAuthAccount],
        eligible: list[ManagedOAuthAccount],
        now_s: float,
    ) -> ManagedOAuthAccount | None:
        if not self._session_affinity_enabled() or not session_id:
            return None
        self._clean_affinity(now_s)
        binding = self._session_affinity.get(session_id)
        if not binding:
            return None
        account_id, _ = binding
        available_by_id = {account.account_id: account for account in available}
        eligible_ids = {account.account_id for account in eligible}
        candidate = available_by_id.get(account_id)
        if candidate is None or account_id not in eligible_ids:
            self._clear_affinity(session_id)
            return None
        self._record_affinity(session_id, account_id, now_s)
        return candidate

    async def get_next_account(
        self,
        *,
        session_id: str | None = None,
        ignore_session_affinity: bool = False,
    ) -> ManagedOAuthAccount | None:
        """Return next usable account and perform proactive refresh."""
        await self._ensure_accounts_loaded()

        rate_limit_idle_polls = 0
        while True:
            now_ms = int(time.time() * 1000)
            now_s = float(now_ms) / 1000.0
            available, eligible = self._available_accounts(now_ms)
            if not available:
                return None

            if not eligible:
                rate_limit_idle_polls += 1
                if rate_limit_idle_polls > self._max_rate_limit_idle_polls:
                    return None
                soonest_until = min(
                    (
                        account.rate_limited_until
                        for account in available
                        if account.rate_limited_until is not None
                    ),
                    default=now_ms,
                )
                wait_seconds = max((soonest_until - now_ms) / 1000.0, 0.0)
                if wait_seconds > 0 and self._max_rate_limit_wait_seconds > 0:
                    sleep_for = min(wait_seconds, self._max_rate_limit_wait_seconds)
                    await asyncio.sleep(sleep_for)
                    continue
                return None

            rate_limit_idle_polls = 0
            selected: ManagedOAuthAccount | None = None
            if not ignore_session_affinity:
                selected = self._get_affinity_candidate(
                    session_id or "",
                    available,
                    eligible,
                    now_s,
                )
            if selected is None:
                selected = await self._select_round_robin_with_lock(eligible)
            if selected is None:
                return None

            try:
                selected = await self._refresh_service.refresh_if_needed(
                    selected,
                    buffer_ms=self._refresh_buffer_ms,
                )
            except ManagedOAuthRefreshError as exc:
                if exc.needs_reauth:
                    selected = selected.mark_needs_reauth()
                    await self._storage.save_account(selected)
                    self._replace_account(selected)
                    if session_id:
                        self._clear_affinity(session_id)
                    continue
                # Soft-fail: continue with non-refreshed account.
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Managed OAuth refresh failed for %s: %s",
                        selected.account_id,
                        exc,
                    )

            self._replace_account(selected)
            self._current_account = selected
            if session_id:
                self._record_affinity(session_id, selected.account_id, now_s)
            return selected

    def get_current_account(self) -> ManagedOAuthAccount | None:
        return self._current_account

    def _replace_account(self, updated: ManagedOAuthAccount) -> None:
        for idx, account in enumerate(self._accounts):
            if account.account_id == updated.account_id:
                self._accounts[idx] = updated
                return

    def update_account(self, updated: ManagedOAuthAccount) -> None:
        """Update account in local cache and current-account pointer."""
        self._replace_account(updated)
        if (
            self._current_account is not None
            and self._current_account.account_id == updated.account_id
        ):
            self._current_account = updated

    async def mark_current_account_used(self) -> None:
        if self._current_account is None:
            return
        updated = self._current_account.mark_used()
        self._current_account = updated
        self._replace_account(updated)
        await self._storage.save_account(updated)

    async def mark_current_account_rate_limited(
        self,
        retry_after_seconds: float | None,
        *,
        codex_usage_limit_fields: dict[str, Any] | None = None,
    ) -> None:
        if self._current_account is None:
            return

        acc = self._current_account
        if codex_usage_limit_fields:
            observed = datetime.now(timezone.utc).isoformat()
            snap = dict(codex_usage_limit_fields)
            snap["observed_at"] = observed
            acc = acc.model_copy(
                update={
                    "last_codex_usage_limit": snap,
                    "updated_at": observed,
                }
            )
        cap = (
            self._rate_limit_local_cooldown_cap_seconds
            if self._rate_limit_local_cooldown_cap_seconds > 0
            else None
        )
        updated = acc.mark_rate_limited(
            retry_after_seconds, local_cooldown_cap_seconds=cap
        )
        self._current_account = updated
        self._replace_account(updated)
        await self._storage.save_account(updated)

    async def rotate_on_rate_limit(
        self,
        *,
        retry_after_seconds: float | None,
        session_id: str | None = None,
        codex_usage_limit_fields: dict[str, Any] | None = None,
    ) -> ManagedOAuthAccount | None:
        await self.mark_current_account_rate_limited(
            retry_after_seconds,
            codex_usage_limit_fields=codex_usage_limit_fields,
        )
        return await self.get_next_account(
            session_id=session_id,
            ignore_session_affinity=True,
        )

    async def rotate_on_auth_failure(
        self,
        *,
        session_id: str | None = None,
    ) -> ManagedOAuthAccount | None:
        if self._current_account is not None:
            failed = self._current_account.mark_auth_failure()
            if failed.consecutive_auth_failures >= 2:
                failed = failed.mark_needs_reauth()
            self._current_account = failed
            self._replace_account(failed)
            await self._storage.save_account(failed)
        return await self.get_next_account(
            session_id=session_id,
            ignore_session_affinity=True,
        )
