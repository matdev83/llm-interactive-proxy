"""
Unit tests for Kiro AccountSelectorService.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from src.connectors.kiro_oauth_auto.account_selector import AccountSelectorService
from src.connectors.kiro_oauth_auto.errors import (
    NoValidAccountsError,
    TokenRefreshError,
)
from src.connectors.kiro_oauth_auto.models import StoredAccount

# Matches @freeze_time("2026-01-19")
BASE_TIME = 1768780800.0  # 2026-01-19 00:00:00 UTC


@pytest.fixture
def account_valid() -> StoredAccount:
    return StoredAccount(
        account_id="a-valid",
        auth_method="builderid",
        region="us-east-1",
        access_token="access.valid",
        refresh_token="refresh.valid",
        client_id="client.valid",
        client_secret="secret.valid",
        expiry_date=int((BASE_TIME + 3600) * 1000),
    )


@pytest.fixture
def account_expired() -> StoredAccount:
    return StoredAccount(
        account_id="a-expired",
        auth_method="builderid",
        region="us-east-1",
        access_token="access.old",
        refresh_token="refresh.old",
        client_id="client.old",
        client_secret="secret.old",
        expiry_date=int((BASE_TIME - 10) * 1000),
    )


@freeze_time("2026-01-19")
class TestAccountSelectorService:
    @pytest.mark.asyncio
    async def test_get_next_account_refreshes_if_expired(
        self, account_expired: StoredAccount
    ) -> None:
        storage = MagicMock()
        storage.load_all_accounts = AsyncMock(return_value=[account_expired])
        storage.save_account = AsyncMock()

        refresh = MagicMock()
        refreshed = account_expired.with_updated_tokens(
            access_token="access.new",
            expiry_date=int((BASE_TIME + 3600) * 1000),
            refresh_token="refresh.new",
        )
        refresh.refresh_account = AsyncMock(return_value=refreshed)

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=300_000,
        )
        await selector.reload_accounts()
        chosen = await selector.get_next_account()
        assert chosen.access_token == "access.new"
        refresh.refresh_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_next_account_skips_refresh_failures(
        self, account_expired: StoredAccount
    ) -> None:
        storage = MagicMock()
        storage.load_all_accounts = AsyncMock(return_value=[account_expired])
        storage.save_account = AsyncMock()

        refresh = MagicMock()
        refresh.refresh_account = AsyncMock(side_effect=TokenRefreshError("nope"))

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=300_000,
        )
        await selector.reload_accounts()
        with pytest.raises(NoValidAccountsError):
            await selector.get_next_account()

    @pytest.mark.asyncio
    async def test_mark_current_account_used_updates_storage(
        self, account_valid: StoredAccount
    ) -> None:
        storage = MagicMock()
        storage.load_all_accounts = AsyncMock(return_value=[account_valid])
        storage.save_account = AsyncMock()

        refresh = MagicMock()
        refresh.refresh_account = AsyncMock()

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=300_000,
            selection_strategy="round-robin",
        )
        await selector.reload_accounts()
        _ = await selector.get_next_account()
        await selector.mark_current_account_used()
        storage.save_account.assert_called_once()
