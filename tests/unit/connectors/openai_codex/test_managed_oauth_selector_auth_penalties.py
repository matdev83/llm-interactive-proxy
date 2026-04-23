"""Auth-failure rotation semantics for managed OAuth account selection."""

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
async def test_rotate_on_auth_failure_preserves_disk_needs_reauth() -> None:
    """Stale in-memory ``needs_reauth`` false must not overwrite disk quarantine."""
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
                needs_reauth=True,
            )
        )
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_b",
                access_token="tb",
                refresh_token="rb",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            selection_strategy="first-available",
        )
        await selector.reload_accounts()
        stale = ManagedOAuthAccount(
            account_id="acct_a",
            access_token="ta",
            refresh_token="ra",
            expiry_date=exp,
            needs_reauth=False,
            consecutive_auth_failures=0,
        )
        selector._current_account = stale

        await selector.rotate_on_auth_failure(session_id=None)

        disk_a = await storage.get_account("acct_a")
        assert disk_a is not None
        assert disk_a.needs_reauth is True
        assert disk_a.consecutive_auth_failures == 0


@pytest.mark.asyncio
async def test_rotate_away_without_auth_penalty_does_not_increment_failures() -> None:
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
        await storage.save_account(
            ManagedOAuthAccount(
                account_id="acct_b",
                access_token="tb",
                refresh_token="rb",
                expiry_date=exp,
            )
        )
        refresh = ManagedOAuthRefreshService(storage, http_client=None)
        selector = ManagedOAuthAccountSelector(
            storage,
            refresh,
            selection_strategy="first-available",
        )
        await selector.reload_accounts()
        selector._current_account = await storage.get_account("acct_a")

        nxt = await selector.rotate_away_without_auth_penalty(session_id=None)
        assert nxt is not None

        disk_a = await storage.get_account("acct_a")
        assert disk_a is not None
        assert disk_a.consecutive_auth_failures == 0
