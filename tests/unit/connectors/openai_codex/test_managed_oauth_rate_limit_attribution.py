"""Regression: managed OAuth 429 attribution and stale local cooldown persistence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest
from src.connectors.openai_codex.credentials import CredentialManager
from src.connectors.openai_codex.managed_oauth_models import (
    ManagedOAuthAccount,
    ManagedOAuthConfig,
)
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


@pytest.mark.asyncio
async def test_handle_rate_limit_persists_to_bound_account_not_selector_current() -> (
    None
):
    """429 handling must mark the handshake account, not whatever selector._current_account is."""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_path = Path(temp_dir) / "managed_oauth"
        storage = ManagedOAuthStorageService(storage_path)
        expires_at = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_a",
                access_token="token_a",
                refresh_token="refresh_a",
                expiry_date=expires_at,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_b",
                access_token="token_b",
                refresh_token="refresh_b",
                expiry_date=expires_at,
            )
        )

        async with httpx.AsyncClient() as client:
            manager = CredentialManager(client)
            manager.configure_managed_oauth(
                ManagedOAuthConfig(
                    enabled=True,
                    storage_path=str(storage_path),
                    accounts="all",
                    selection_strategy="round-robin",
                    refresh_buffer_seconds=300,
                    session_affinity_ttl_seconds=3600,
                    session_affinity_max_entries=100,
                    allow_legacy_fallback=False,
                    max_rate_limit_wait_seconds=0.01,
                )
            )
            await manager.initialize(auth_path=None)

            sel = manager._managed_selector
            await sel.reload_accounts()
            acc_a = sel.get_account_by_id("acct_a")
            acc_b = sel.get_account_by_id("acct_b")
            assert acc_a is not None and acc_b is not None
            sel._current_account = acc_b

            upstream = {
                "error": {
                    "type": "usage_limit_reached",
                    "message": "limit",
                    "plan_type": "plus",
                    "resets_in_seconds": 120.0,
                }
            }
            rotated = await manager.handle_rate_limit(
                30.0,
                session_id="sess",
                upstream_codex_error=upstream,
                managed_oauth_account_id="acct_a",
            )
            assert rotated is True

        on_a = await storage.get_account("acct_a")
        on_b = await storage.get_account("acct_b")
        assert on_a is not None and on_b is not None
        assert on_a.last_codex_usage_limit is not None
        assert on_a.last_codex_usage_limit.get("plan_type") == "plus"
        assert on_a.rate_limited_until is not None
        assert on_b.last_codex_usage_limit is None
        assert on_b.rate_limited_until is None


@pytest.mark.asyncio
async def test_record_codex_quota_headers_targets_managed_oauth_account_id() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_path = Path(temp_dir) / "managed_oauth"
        storage = ManagedOAuthStorageService(storage_path)
        expires_at = 9_999_999_999_999
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_a",
                access_token="token_a",
                refresh_token="refresh_a",
                expiry_date=expires_at,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_b",
                access_token="token_b",
                refresh_token="refresh_b",
                expiry_date=expires_at,
            )
        )

        async with httpx.AsyncClient() as client:
            manager = CredentialManager(client)
            manager.configure_managed_oauth(
                ManagedOAuthConfig(
                    enabled=True,
                    storage_path=str(storage_path),
                    accounts="all",
                    selection_strategy="round-robin",
                    refresh_buffer_seconds=300,
                    session_affinity_ttl_seconds=3600,
                    session_affinity_max_entries=100,
                    allow_legacy_fallback=False,
                    max_rate_limit_wait_seconds=0.01,
                )
            )
            await manager.initialize(auth_path=None)

            sel = manager._managed_selector
            await sel.reload_accounts()
            acc_a = sel.get_account_by_id("acct_a")
            acc_b = sel.get_account_by_id("acct_b")
            assert acc_a is not None and acc_b is not None
            sel._current_account = acc_b

            await manager.record_codex_quota_headers(
                {"X-Codex-Plan-Type": "team"},
                force=True,
                managed_oauth_account_id="acct_a",
            )

        on_a = await storage.get_account("acct_a")
        on_b = await storage.get_account("acct_b")
        assert on_a is not None and on_b is not None
        assert on_a.last_codex_quota_headers is not None
        assert on_b.last_codex_quota_headers is None


def test_cleared_if_local_rate_limit_expired_clears_elapsed_cooldown() -> None:
    base_ms = 1_700_000_000_000
    past = base_ms - 60_000
    acc = ManagedOAuthAccount(
        account_id="x1",
        access_token="t",
        refresh_token="r",
        rate_limited_until=past,
    )
    cleared = acc.cleared_if_local_rate_limit_expired(past + 1)
    assert cleared.rate_limited_until is None


@pytest.mark.asyncio
async def test_load_all_accounts_persists_cleared_expired_rate_limited_until() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_path = Path(temp_dir) / "managed_oauth"
        storage = ManagedOAuthStorageService(storage_path)
        past = 1_700_000_000_000 - 3_600_000
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="stale_rl",
                access_token="t",
                refresh_token="r",
                rate_limited_until=past,
            )
        )
        await storage.load_all_accounts()
        raw = (storage_path / "stale_rl.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data.get("rate_limited_until") is None
