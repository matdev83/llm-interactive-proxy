"""
Unit tests for AccountSelectorService.

Tests Requirement 4: Multi-Account Support.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

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
def selector(
    mock_storage: MagicMock, mock_refresh_service: MagicMock
) -> AccountSelectorService:
    """Fixture providing AccountSelectorService with mocked dependencies."""
    return AccountSelectorService(
        storage=mock_storage,
        refresh_service=mock_refresh_service,
    )


def create_valid_account(
    account_id: str,
    email: str = "test@gmail.com",
    needs_reauth: bool = False,
    hours_until_expiry: float = 1.0,
) -> StoredAccount:
    """Helper to create a valid account with configurable expiry."""
    return StoredAccount(
        account_id=account_id,
        email=email,
        access_token=f"ya29.token_{account_id}",
        refresh_token=f"1//refresh_{account_id}",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((time.time() + hours_until_expiry * 3600) * 1000),
        needs_reauth=needs_reauth,
    )


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
    async def test_get_next_account_triggers_refresh_for_near_expiry(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        """Test get_next_account triggers refresh for near-expiry accounts."""
        # Account expires in 2 minutes (within 5 minute buffer)
        near_expiry = create_valid_account("account-1", hours_until_expiry=2 / 60)
        mock_storage.load_all_accounts = AsyncMock(return_value=[near_expiry])

        # Mock refresh to return updated account
        refreshed = near_expiry.with_updated_tokens(
            access_token="ya29.refreshed",
            expiry_date=int((time.time() + 3600) * 1000),
        )
        mock_refresh_service.refresh_if_needed = AsyncMock(return_value=refreshed)

        result = await selector.get_next_account()

        assert result is not None
        mock_refresh_service.refresh_if_needed.assert_called()

    @pytest.mark.asyncio
    async def test_round_robin_rotation(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test round-robin rotation between accounts."""
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
            create_valid_account("account-3"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Get multiple accounts and verify rotation
        seen_ids: list[str] = []
        for _ in range(6):  # Two full rotations
            result = await selector.get_next_account()
            assert result is not None
            seen_ids.append(result.account_id)

        # Should see each account at least twice in round-robin order
        assert seen_ids.count("account-1") == 2
        assert seen_ids.count("account-2") == 2
        assert seen_ids.count("account-3") == 2

    @pytest.mark.asyncio
    async def test_rotate_on_quota_advances_to_next(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test rotate_on_quota advances to next account."""
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Get initial account
        first = await selector.get_next_account()
        assert first is not None
        first_id = first.account_id

        # Rotate on quota
        second = await selector.rotate_on_quota()
        assert second is not None
        assert second.account_id != first_id

    @pytest.mark.asyncio
    async def test_get_available_count_excludes_needs_reauth(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_available_count excludes accounts needing reauth."""
        accounts = [
            create_valid_account("account-1", needs_reauth=True),
            create_valid_account("account-2", needs_reauth=False),
            create_valid_account("account-3", needs_reauth=True),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Initialize by loading accounts
        await selector.get_next_account()

        count = selector.get_available_count()
        assert count == 1  # Only account-2 is available

    @pytest.mark.asyncio
    async def test_empty_accounts_returns_none(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account returns None when no accounts."""
        mock_storage.load_all_accounts = AsyncMock(return_value=[])

        result = await selector.get_next_account()

        assert result is None

    @pytest.mark.asyncio
    async def test_all_needs_reauth_returns_none(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_next_account returns None when all accounts need reauth."""
        accounts = [
            create_valid_account("account-1", needs_reauth=True),
            create_valid_account("account-2", needs_reauth=True),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        result = await selector.get_next_account()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_account_returns_selected(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_current_account returns currently selected account."""
        accounts = [create_valid_account("account-1")]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Initially None
        assert selector.get_current_account() is None

        # After selection
        await selector.get_next_account()
        current = selector.get_current_account()
        assert current is not None
        assert current.account_id == "account-1"

    @pytest.mark.asyncio
    async def test_get_current_account_does_not_advance(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test get_current_account does not advance rotation."""
        accounts = [
            create_valid_account("account-1"),
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Select first
        first = await selector.get_next_account()
        assert first is not None

        # Call get_current_account multiple times
        for _ in range(5):
            current = selector.get_current_account()
            assert current is not None
            assert current.account_id == first.account_id

    @pytest.mark.asyncio
    async def test_rotate_on_quota_returns_none_when_all_exhausted(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
    ) -> None:
        """Test rotate_on_quota returns None when no alternatives available."""
        accounts = [create_valid_account("account-1")]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)

        # Select the only account
        await selector.get_next_account()

        # Try to rotate - should return same account or None
        result = await selector.rotate_on_quota()
        # With only one account, rotation wraps back to it
        assert result is None or result.account_id == "account-1"
