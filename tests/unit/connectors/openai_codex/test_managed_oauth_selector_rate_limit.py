"""Regression tests for managed OAuth selector rate-limit rotation and wait bounds."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_refresh import ManagedOAuthRefreshService
from src.connectors.openai_codex.managed_oauth_selector import (
    ManagedOAuthAccountSelector,
)
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService

from tests.unit.fixtures.markers import real_time


@pytest.mark.asyncio
async def test_get_next_account_prefers_non_rate_limited_account() -> None:
    """After marking the current account limited, selector must return another account."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_a",
                access_token="token_a",
                refresh_token="refresh_a",
                expiry_date=exp,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_b",
                access_token="token_b",
                refresh_token="refresh_b",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            max_rate_limit_wait_seconds=0.01,
            max_rate_limit_idle_polls=8,
            rate_limit_local_cooldown_cap_seconds=600.0,
        )
        await selector.reload_accounts()
        first = await selector.get_next_account(
            session_id="sess-1", ignore_session_affinity=True
        )
        assert first is not None
        assert first.account_id in {"acct_a", "acct_b"}

        await selector.mark_current_account_rate_limited(
            3600.0, codex_usage_limit_fields=None
        )
        second = await selector.get_next_account(
            session_id="sess-1", ignore_session_affinity=True
        )
        assert second is not None
        assert second.account_id != first.account_id


@pytest.mark.asyncio
async def test_get_next_account_returns_none_when_all_rate_limited_and_polls_exhausted() -> (
    None
):
    """With every account locally rate-limited, bounded idle polls must end (no infinite loop)."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="only_a",
                access_token="ta",
                refresh_token="ra",
                expiry_date=exp,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="only_b",
                access_token="tb",
                refresh_token="rb",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            max_rate_limit_wait_seconds=0.001,
            max_rate_limit_idle_polls=4,
            rate_limit_local_cooldown_cap_seconds=3600.0,
        )
        await selector.reload_accounts()
        first = await selector.get_next_account(ignore_session_affinity=True)
        assert first is not None
        await selector.mark_current_account_rate_limited(86_400.0)
        second = await selector.get_next_account(ignore_session_affinity=True)
        assert second is not None
        await selector.mark_current_account_rate_limited(86_400.0)
        third = await selector.get_next_account(ignore_session_affinity=True)
        assert third is None


@pytest.mark.asyncio
@real_time(
    reason="Compare rate_limited_until from selector against wall clock for cap span."
)
async def test_mark_current_account_rate_limited_applies_local_cap() -> None:
    """Selector must pass local cooldown cap into mark_rate_limited (short local window)."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="cap_test",
                access_token="t",
                refresh_token="r",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            rate_limit_local_cooldown_cap_seconds=90.0,
        )
        await selector.reload_accounts()
        acc = await selector.get_next_account(ignore_session_affinity=True)
        assert acc is not None
        await selector.mark_current_account_rate_limited(
            999_999.0, codex_usage_limit_fields=None
        )
        updated = selector.get_current_account()
        assert updated is not None
        assert updated.rate_limited_until is not None
        now_ms = int(time.time() * 1000)
        span_ms = updated.rate_limited_until - now_ms
        assert span_ms <= 95_000
