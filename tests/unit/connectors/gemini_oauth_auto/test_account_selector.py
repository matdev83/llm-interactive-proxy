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
    async def test_get_next_account_refresh_failure_needs_reauth(
        self,
        selector: AccountSelectorService,
        mock_storage: MagicMock,
        mock_refresh_service: MagicMock,
    ) -> None:
        """Test get_next_account handles refresh failure with needs_reauth."""
        from src.connectors.gemini_oauth_auto.errors import TokenRefreshError
        
        accounts = [
            create_valid_account("account-1", hours_until_expiry=0),  # Expired
            create_valid_account("account-2"),
        ]
        mock_storage.load_all_accounts = AsyncMock(return_value=accounts)
        
        # Mock first refresh to fail with needs_reauth
        mock_refresh_service.refresh_if_needed.side_effect = [
            TokenRefreshError("Invalid grant", needs_reauth=True, account_id="account-1"),
            accounts[1] # Second one succeeds
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
        
        mock_refresh_service.refresh_if_needed.side_effect = TokenRefreshError("Transient error")
        
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

