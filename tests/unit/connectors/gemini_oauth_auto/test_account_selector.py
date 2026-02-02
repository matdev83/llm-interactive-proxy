"""
Unit tests for AccountSelectorService.

Tests Requirement 4: Multi-Account Support.
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.models import StoredAccount


@pytest.fixture
def mock_storage() -> MagicMock:
    """Fixture providing mock token storage."""
    storage = MagicMock()
    storage.load_all_accounts = AsyncMock(return_value=[])
    storage.save_account = AsyncMock()
    return storage


@pytest.fixture
def mock_refresh_service() -> MagicMock:
    """Fixture providing mock token refresh service."""
    refresh = MagicMock()
    refresh.refresh_if_needed = AsyncMock(side_effect=lambda acc, **kw: acc)
    return refresh


@pytest.fixture
def mock_notification_service() -> MagicMock:
    """Fixture providing mock notification service."""
    service = MagicMock()
    # By default, notifications are enabled in tests
    service.is_enabled = True

    async def send_mock(title, message):
        if not service.is_enabled:
            return None
        return await service._real_send(title, message)

    service._real_send = AsyncMock(return_value="notification-id")
    service.send_notification = AsyncMock(side_effect=send_mock)
    return service


@pytest.fixture
def selector(
    mock_storage: MagicMock,
    mock_refresh_service: MagicMock,
    mock_notification_service: MagicMock,
) -> AccountSelectorService:
    """Fixture providing AccountSelectorService with mocked dependencies."""
    return AccountSelectorService(
        storage=mock_storage,
        refresh_service=mock_refresh_service,
        notification_service=mock_notification_service,
    )


def create_valid_account(
    account_id: str,
    email: str = "test@gmail.com",
    needs_reauth: bool = False,
    hours_until_expiry: float = 1.0,
) -> StoredAccount:
    """Helper to create a valid account with configurable expiry.

    Uses a fixed base time to avoid direct time.time() calls flagged by linter.
    Base time matches @freeze_time("2026-01-19") used in tests.
    """
    base_time = 1768780800.0  # 2026-01-19 00:00:00 UTC
    return StoredAccount(
        account_id=account_id,
        email=email,
        access_token=f"ya29.token_{account_id}",
        refresh_token=f"1//refresh_{account_id}",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((base_time + hours_until_expiry * 3600) * 1000),
        needs_reauth=needs_reauth,
    )


@freeze_time("2026-01-19")
class TestAccountSelectorService:
    """Tests for AccountSelectorService."""

    @pytest.mark.asyncio
    async def test_get_next_account_returns_valid_account(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account returns a valid account."""
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        result = await selector.get_next_account()

        assert result is not None
        assert result.account_id in ["account-1", "account-2"]

    @pytest.mark.asyncio
    async def test_get_next_account_skips_needs_reauth(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account skips accounts with needs_reauth=True."""
        accounts = [
            create_valid_account("account-1", needs_reauth=True),
            create_valid_account("account-2", needs_reauth=False),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        result = await selector.get_next_account()

        assert result is not None
        assert result.account_id == "account-2"

    @pytest.mark.asyncio
    async def test_get_next_account_refresh_failure_needs_reauth(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        """Test get_next_account handles refresh failure with needs_reauth."""
        from src.connectors.gemini_oauth_auto.account_selector import (
            TokenRefreshError as SelectorTokenRefreshError,
        )
        from src.connectors.gemini_oauth_auto.errors import TokenRefreshError

        print(f"DEBUG: Test TokenRefreshError id: {id(TokenRefreshError)}")
        print(f"DEBUG: Selector TokenRefreshError id: {id(SelectorTokenRefreshError)}")

        accounts = [
            create_valid_account("account-1", hours_until_expiry=0),  # Expired
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Mock first refresh to fail with needs_reauth
        mock_refresh_service.refresh_if_needed.side_effect = [
            TokenRefreshError(
                "Invalid grant", needs_reauth=True, account_id="account-1"
            ),
            accounts[1],  # Second one succeeds
        ]

        result = await selector.get_next_account()

        assert result is not None
        assert result.account_id == "account-2"
        # Verify account-1 was updated in list (needs_reauth=True)
        # We can't check internal list directly easily, but we can verify it was skipped

    @pytest.mark.asyncio
    async def test_get_next_account_refresh_failure_other(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        """Test get_next_account handles other refresh failures by using account anyway."""
        from src.connectors.gemini_oauth_auto.errors import TokenRefreshError

        account = create_valid_account("account-1", hours_until_expiry=0)
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        mock_refresh_service.refresh_if_needed.side_effect = TokenRefreshError(
            "Transient error"
        )

        result = await selector.get_next_account()

        assert result is not None
        assert result.account_id == "account-1"

    @pytest.mark.asyncio
    async def test_reload_accounts(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test reload_accounts resets state and loads from storage."""
        mock_storage.load_all_accounts.return_value = [create_valid_account("acc")]

        await selector.reload_accounts()

        assert selector.get_available_count() == 1
        mock_storage.load_all_accounts.assert_called()

    @pytest.mark.asyncio
    async def test_allowlist_filters_accounts(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        """Configured allowlist should restrict which accounts are eligible."""
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            allowed_account_ids={"account-2"},
        )

        selected = await selector.get_next_account()
        assert selected is not None
        assert selected.account_id == "account-2"

    @pytest.mark.asyncio
    async def test_waits_for_shortest_rate_limit(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When all accounts are rate limited, wait for the shortest window."""
        from src.connectors.gemini_oauth_auto import (
            account_selector as module_under_test,
        )

        base_time = 1768780800.0
        base_ms = int(base_time * 1000)
        account1 = create_valid_account("account-1")
        account2 = create_valid_account("account-2")
        account1 = account1.model_copy(update={"rate_limited_until": base_ms + 5000})
        account2 = account2.model_copy(update={"rate_limited_until": base_ms + 10000})

        mock_storage.load_all_accounts = AsyncMock(return_value=[account1, account2])

        sleep_mock = AsyncMock()
        monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

        times = iter([base_time, base_time + 5.1])

        def fake_time() -> float:
            return next(times, base_time + 5.1)

        monkeypatch.setattr(module_under_test.time, "time", fake_time)

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
        )

        selected = await selector.get_next_account()

        assert selected is not None
        assert selected.account_id == "account-1"
        assert sleep_mock.await_count == 1
        assert sleep_mock.await_args is not None
        assert sleep_mock.await_args.args[0] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_random_strategy_picks_different_account(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        accounts = [
            create_valid_account("acc-1"),
            create_valid_account("acc-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            selection_strategy="random",
        )

        first = await selector.get_next_account()
        assert first is not None

        second = await selector.get_next_account()
        assert second is not None
        assert second.account_id != first.account_id

    @pytest.mark.asyncio
    async def test_first_available_strategy(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        accounts = [
            create_valid_account("acc-1"),
            create_valid_account("acc-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            selection_strategy="first-available",
        )

        first = await selector.get_next_account()
        assert first is not None
        assert first.account_id == "acc-1"

        second = await selector.get_next_account()
        assert second is not None
        assert second.account_id == "acc-1"

    @pytest.mark.asyncio
    async def test_mark_current_account_used(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        account = create_valid_account("acc-1")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        await selector.get_next_account()
        current = selector.get_current_account()
        assert current is not None
        assert current.last_used is None

        await selector.mark_current_account_used()

        updated = selector.get_current_account()
        assert updated is not None
        assert updated.last_used is not None
        mock_storage.save_account.assert_called()

        assert selector._accounts[0].last_used is not None

    @pytest.mark.asyncio
    async def test_get_next_account_returns_none_when_no_accounts(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account returns None when no accounts available."""
        mock_storage.load_all_accounts = AsyncMock(return_value=[])

        result = await selector.get_next_account()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_next_account_returns_none_when_all_reauth(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account returns None when all accounts need reauth."""
        accounts = [
            create_valid_account("account-1", needs_reauth=True),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        result = await selector.get_next_account()

        assert result is None

    @pytest.mark.asyncio
    async def test_session_affinity_reuses_account(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            selection_strategy="session-affinity",
        )

        first = await selector.get_next_account(session_id="session-a")
        second = await selector.get_next_account(session_id="session-a")
        third = await selector.get_next_account(session_id="session-b")

        assert first is not None
        assert second is not None
        assert third is not None
        assert first.account_id == second.account_id
        assert third.account_id != first.account_id

    @pytest.mark.asyncio
    async def test_session_affinity_rotates_when_rate_limited(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        base_time = 1768780800.0
        base_ms = int(base_time * 1000)
        account1 = create_valid_account("account-1")
        account2 = create_valid_account("account-2")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account1, account2])

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            selection_strategy="session-affinity",
        )

        first = await selector.get_next_account(session_id="session-a")
        assert first is not None
        assert first.account_id == "account-1"

        rate_limited = account1.model_copy(
            update={"rate_limited_until": base_ms + 5000}
        )
        selector.update_account(rate_limited)

        second = await selector.get_next_account(session_id="session-a")
        assert second is not None
        assert second.account_id == "account-2"

    @pytest.mark.asyncio
    async def test_session_affinity_waits_for_short_rate_limit(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        account1 = create_valid_account("account-1")
        account2 = create_valid_account("account-2")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account1, account2])

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            selection_strategy="session-affinity",
            session_affinity_max_wait_seconds=2.0,
        )

        first = await selector.get_next_account(session_id="session-a")
        assert first is not None
        assert first.account_id == "account-1"

        base_time = 1768780800.0
        base_ms = int(base_time * 1000)
        rate_limited = account1.model_copy(
            update={"rate_limited_until": base_ms + 1000}
        )
        selector.update_account(rate_limited)

        times = iter([base_time, base_time, base_time + 1.2])

        def fake_time() -> float:
            return next(times, base_time + 1.2)

        monkeypatch.setattr(time, "time", fake_time)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        second = await selector.get_next_account(session_id="session-a")
        assert second is not None
        assert second.account_id == "account-1"

    @pytest.mark.asyncio
    async def test_mark_current_account_used_no_current(
        self,
        selector: AccountSelectorService,
    ) -> None:
        """Test mark_current_account_used does nothing if no current account."""
        await selector.mark_current_account_used()
        # Should not raise

    @pytest.mark.asyncio
    async def test_rotate_on_quota_no_alternatives(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test rotate_on_quota logs warning when only one account available."""
        accounts = [
            create_valid_account("account-1"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        await selector.get_next_account()  # Sets current

        with caplog.at_level(logging.WARNING):
            result = await selector.rotate_on_quota()

        assert result is None
        assert "Cannot rotate: only 1 account(s) available" in caplog.text

    @pytest.mark.asyncio
    async def test_select_account_from_available_empty(
        self,
        selector: AccountSelectorService,
    ) -> None:
        """Test _select_account_from_available returns None for empty list."""
        assert selector._select_account_from_available([]) is None

    @pytest.mark.asyncio
    async def test_mark_current_account_blocked_sends_notification(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that blocking an account sends OS notification exactly once."""
        account = create_valid_account("account-blocked-1")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        await selector.get_next_account()
        current = selector.get_current_account()
        assert current is not None
        assert current.account_id == "account-blocked-1"

        await selector.mark_current_account_blocked("Account requires verification")

        mock_notification_service.send_notification.assert_called_once()
        call_args = mock_notification_service.send_notification.call_args
        assert call_args is not None
        assert call_args.kwargs["title"] == "Gemini OAuth account needs verification"
        assert "test@gmail.com" in call_args.kwargs["message"]
        assert "requires additional verification" in call_args.kwargs["message"]
        assert "No other accounts available!" in call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_mark_current_account_blocked_no_duplicate_notification(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that blocking same account twice only sends one notification."""
        account = create_valid_account("account-blocked-2")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        await selector.get_next_account()

        await selector.mark_current_account_blocked("First block reason")
        assert mock_notification_service.send_notification.call_count == 1

        selector._current_account = account
        await selector.mark_current_account_blocked("Second block reason")
        assert mock_notification_service.send_notification.call_count == 1

    @pytest.mark.asyncio
    async def test_mark_current_account_blocked_different_accounts_send_separate_notifications(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that blocking different accounts sends separate notifications."""
        account1 = create_valid_account("account-1")
        account2 = create_valid_account("account-2")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account1, account2])

        await selector.get_next_account()
        await selector.mark_current_account_blocked("Account 1 blocked")
        assert mock_notification_service.send_notification.call_count == 1

        await selector.get_next_account()
        await selector.mark_current_account_blocked("Account 2 blocked")
        assert mock_notification_service.send_notification.call_count == 2

    @pytest.mark.asyncio
    async def test_mark_current_account_blocked_no_current_account(
        self,
        selector: AccountSelectorService,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that blocking with no current account does not send notification."""
        await selector.mark_current_account_blocked("Some reason")
        mock_notification_service.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_current_account_blocked_notification_failure_is_non_blocking(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that notification failure does not block account blocking."""
        account = create_valid_account("account-fail-test")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        await selector.get_next_account()

        # Side effect on the underlying mock to simulate provider failure
        mock_notification_service._real_send.side_effect = Exception(
            "Notification failed"
        )

        await selector.mark_current_account_blocked("Block reason")

        mock_notification_service.send_notification.assert_called_once()
        assert account.account_id in selector._blocked_account_ids

    @pytest.mark.asyncio
    async def test_notifications_disabled_does_not_send_notification(
        self,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that notifications are not sent when disabled."""
        mock_notification_service.is_enabled = False
        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh_service,
            notification_service=mock_notification_service,
        )

        account = create_valid_account("account-no-notify")
        mock_storage.load_all_accounts = AsyncMock(return_value=[account])

        await selector.get_next_account()

        await selector.mark_current_account_blocked("Block reason")

        mock_notification_service._real_send.assert_not_called()
        assert account.account_id in selector._blocked_account_ids

    @pytest.mark.asyncio
    async def test_notification_includes_other_available_accounts_count(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_notification_service: MagicMock,
    ) -> None:
        """Test that notification includes count of other available accounts."""
        # Create 3 accounts, only one will be blocked
        account1 = create_valid_account("account-blocked")
        account2 = create_valid_account("account-available-2")
        account3 = create_valid_account("account-available-3")
        mock_storage.load_all_accounts = AsyncMock(
            return_value=[account1, account2, account3]
        )

        await selector.get_next_account()
        current = selector.get_current_account()
        assert current is not None
        assert current.account_id == "account-blocked"

        await selector.mark_current_account_blocked("Account flagged")

        mock_notification_service.send_notification.assert_called_once()
        call_args = mock_notification_service.send_notification.call_args
        assert call_args is not None
        assert call_args.kwargs["title"] == "Gemini OAuth account needs verification"
        # Should show 2 other available accounts
        assert "Other available accounts: 2" in call_args.kwargs["message"]

    def test_notifications_enabled_property(self) -> None:
        """Test the notifications_enabled property."""
        mock_storage = MagicMock()
        mock_refresh = MagicMock()

        # Test with no service (False)
        selector_no_service = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh,
            notification_service=None,
        )
        assert selector_no_service.notifications_enabled is False

        # Test with service enabled
        mock_service_enabled = MagicMock()
        mock_service_enabled.is_enabled = True
        selector_enabled = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh,
            notification_service=mock_service_enabled,
        )
        assert selector_enabled.notifications_enabled is True

        # Test with service disabled
        mock_service_disabled = MagicMock()
        mock_service_disabled.is_enabled = False
        selector_disabled = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh,
            notification_service=mock_service_disabled,
        )
        assert selector_disabled.notifications_enabled is False

    def test_notification_service_setter(self) -> None:
        """Test the notification_service setter."""
        mock_storage = MagicMock()
        mock_refresh = MagicMock()

        selector = AccountSelectorService(
            storage=mock_storage,
            refresh_service=mock_refresh,
            notification_service=None,
        )
        assert selector.notification_service is None
        assert selector.notifications_enabled is False

        mock_service = MagicMock()
        mock_service.is_enabled = True
        selector.notification_service = mock_service
        assert selector.notification_service is mock_service
        assert selector.notifications_enabled is True
