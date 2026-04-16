"""Allowlist behaviour for managed OAuth account selection."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_refresh import ManagedOAuthRefreshService
from src.connectors.openai_codex.managed_oauth_selector import (
    ManagedOAuthAccountSelector,
)
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


@pytest.mark.asyncio
async def test_allowlist_accepts_chatgpt_account_id() -> None:
    """Explicit allowlist entries may use ChatGPT UUID instead of storage account_id."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        cgpt = "b8db4c23-9937-49ef-97d6-53614f8e9590"
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="friendly_name",
                chatgpt_account_id=cgpt,
                access_token="token_a",
                refresh_token="refresh_a",
                expiry_date=exp,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="other",
                chatgpt_account_id="22222222-2222-2222-2222-222222222222",
                access_token="token_b",
                refresh_token="refresh_b",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            allowed_account_ids={cgpt},
        )
        await selector.reload_accounts()
        eligible = await selector.list_eligible_account_ids()
        assert eligible == ["friendly_name"]


@pytest.mark.asyncio
async def test_allowlist_still_accepts_storage_account_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_a",
                access_token="ta",
                refresh_token="ra",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            allowed_account_ids={"acct_a"},
        )
        await selector.reload_accounts()
        eligible = await selector.list_eligible_account_ids()
        assert eligible == ["acct_a"]


@pytest.mark.asyncio
async def test_eligibility_debug_snapshot_allowlist_flags() -> None:
    """Regression: diagnostics must show allowlist_ok false when id does not match."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        cgpt = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="allowed_slug",
                chatgpt_account_id=cgpt,
                access_token="ta",
                refresh_token="ra",
                expiry_date=exp,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="blocked_slug",
                chatgpt_account_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                access_token="tb",
                refresh_token="rb",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            allowed_account_ids={cgpt},
        )
        await selector.reload_accounts()
        rows = selector.eligibility_debug_snapshot()
        assert len(rows) == 2
        by_id = {r["account_id"]: r for r in rows}
        assert by_id["allowed_slug"]["allowlist_ok"] is True
        assert by_id["allowed_slug"]["eligible_for_traffic"] is True
        assert by_id["blocked_slug"]["allowlist_ok"] is False
        assert by_id["blocked_slug"]["eligible_for_traffic"] is False
        for r in rows:
            assert set(r.keys()) >= {
                "account_id",
                "chatgpt_account_id",
                "email",
                "allowlist_ok",
                "needs_reauth",
                "local_rate_limited",
                "rate_limited_until_ms",
                "eligible_for_traffic",
            }


@pytest.mark.asyncio
async def test_eligibility_debug_snapshot_needs_reauth_not_eligible() -> None:
    """Regression: needs_reauth must surface as ineligible for traffic."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="stale",
                access_token="t",
                refresh_token="r",
                expiry_date=exp,
                needs_reauth=True,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(storage, refresh)
        await selector.reload_accounts()
        rows = selector.eligibility_debug_snapshot()
        assert len(rows) == 1
        r = rows[0]
        assert r["needs_reauth"] is True
        assert r["allowlist_ok"] is True
        assert r["eligible_for_traffic"] is False


@pytest.mark.asyncio
async def test_eligibility_debug_snapshot_local_rate_limit() -> None:
    """Regression: after mark_current_account_rate_limited, snapshot shows local RL."""
    with tempfile.TemporaryDirectory() as tmp:
        storage_path = Path(tmp) / "oauth"
        storage = ManagedOAuthStorageService(str(storage_path))
        exp = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="rl_a",
                access_token="ta",
                refresh_token="ra",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            rate_limit_local_cooldown_cap_seconds=600.0,
        )
        await selector.reload_accounts()
        first = await selector.get_next_account(ignore_session_affinity=True)
        assert first is not None
        await selector.mark_current_account_rate_limited(3600.0)
        rows = selector.eligibility_debug_snapshot()
        rl_row = next(r for r in rows if r["account_id"] == first.account_id)
        assert rl_row["local_rate_limited"] is True
        assert rl_row["rate_limited_until_ms"] is not None
        assert rl_row["eligible_for_traffic"] is False
