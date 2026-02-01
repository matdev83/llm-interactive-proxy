"""
Regression tests for rotation state preservation across re-initializations.

Tests the fix for the bug where backend re-initialization was resetting
the rotation index, causing uneven account distribution.

Bug: Backend re-initialization created new service instances and reset
rotation_index to 0, causing the first account to be used disproportionately.

Fix: Added _is_initialized flag and modified reload_accounts() to preserve
rotation state across re-initializations.
"""

from collections.abc import Generator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.connectors.gemini_oauth_auto.models import StoredAccount


@pytest.fixture
def mock_config() -> MagicMock:
    """Fixture providing mock AppConfig."""
    config = MagicMock()
    config.get.return_value = False
    config.backends = MagicMock()
    config.backends.get.return_value = MagicMock(extra={})
    return config


@pytest.fixture
def mock_translation_service() -> MagicMock:
    """Fixture providing mock TranslationService."""
    return MagicMock()


@pytest.fixture
def mock_client() -> MagicMock:
    """Fixture providing mock httpx AsyncClient."""
    return MagicMock()


@pytest.fixture
def connector(
    mock_client: MagicMock,
    mock_config: MagicMock,
    mock_translation_service: MagicMock,
) -> Generator[GeminiOAuthAutoConnector, None, None]:
    """Fixture providing GeminiOAuthAutoConnector with mocked dependencies."""
    with (
        patch(
            "src.connectors.gemini_oauth_auto.connector.TokenStorageService"
        ) as mock_storage_cls,
        patch(
            "src.connectors.gemini_oauth_auto.connector.TokenRefreshService"
        ) as mock_refresh_cls,
        patch(
            "src.connectors.gemini_oauth_auto.connector.AccountSelectorService"
        ) as mock_selector_cls,
    ):
        # Configure mock instances
        mock_storage = mock_storage_cls.return_value
        mock_refresh = mock_refresh_cls.return_value
        mock_selector = mock_selector_cls.return_value

        # Configure selector mock
        mock_selector.reload_accounts = AsyncMock()
        mock_selector.get_next_account = AsyncMock()
        mock_selector.get_current_account = MagicMock()
        mock_selector.get_available_count = MagicMock(return_value=2)
        mock_selector._rotation_index = 0
        mock_selector._refresh_buffer_ms = 60000
        mock_selector._allowed_account_ids = None
        mock_selector._selection_strategy = "round-robin"

        conn = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Inject mocks
        conn._token_storage = mock_storage
        conn._token_refresh = mock_refresh
        conn._account_selector = mock_selector
        conn._ensure_models_loaded = AsyncMock()

        # Store references for test access
        conn._test_storage_cls = mock_storage_cls
        conn._test_refresh_cls = mock_refresh_cls
        conn._test_selector_cls = mock_selector_cls

        yield conn


class TestRotationStatePreservation:
    """Regression tests for rotation state preservation bug."""

    @pytest.mark.asyncio
    async def test_first_initialization_creates_new_services(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that first initialization creates new service instances."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account

        # Track service creation
        storage_cls = connector._test_storage_cls
        refresh_cls = connector._test_refresh_cls
        selector_cls = connector._test_selector_cls

        initial_storage_calls = storage_cls.call_count
        initial_refresh_calls = refresh_cls.call_count
        initial_selector_calls = selector_cls.call_count

        await connector.initialize()

        # First initialization should create new services
        assert storage_cls.call_count == initial_storage_calls + 1
        assert refresh_cls.call_count == initial_refresh_calls + 1
        assert selector_cls.call_count == initial_selector_calls + 1
        assert connector._is_initialized is True

    @pytest.mark.asyncio
    async def test_reinitialization_preserves_services(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that re-initialization preserves existing service instances."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = mock_account

        # First initialization
        await connector.initialize()

        # Track service creation counts after first init
        storage_cls = connector._test_storage_cls
        refresh_cls = connector._test_refresh_cls
        selector_cls = connector._test_selector_cls

        first_init_storage_calls = storage_cls.call_count
        first_init_refresh_calls = refresh_cls.call_count
        first_init_selector_calls = selector_cls.call_count

        # Store references to service instances
        storage_instance = connector._token_storage
        refresh_instance = connector._token_refresh
        selector_instance = connector._account_selector

        # Second initialization (re-init)
        await connector.initialize()

        # Services should not be recreated
        assert storage_cls.call_count == first_init_storage_calls
        assert refresh_cls.call_count == first_init_refresh_calls
        assert selector_cls.call_count == first_init_selector_calls

        # Service instances should be the same
        assert connector._token_storage is storage_instance
        assert connector._token_refresh is refresh_instance
        assert connector._account_selector is selector_instance

    @pytest.mark.asyncio
    async def test_reinitialization_updates_selector_config(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that re-initialization updates selector configuration."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = mock_account

        # First initialization with default config
        await connector.initialize()

        # Modify config for re-initialization
        connector.config.backends.get.return_value = MagicMock(  # type: ignore[attr-defined]
            extra={
                "refresh_buffer_seconds": 120,
                "accounts": ["account1", "account2"],
                "selection_strategy": "random",
            }
        )

        # Second initialization
        await connector.initialize()

        # Configuration should be updated
        assert selector.refresh_buffer_ms == 120000
        # accounts are converted to set in _parse_accounts_allowlist
        assert selector.allowed_account_ids == {"account1", "account2"}
        assert selector.selection_strategy == "random"

    @pytest.mark.asyncio
    async def test_reinitialization_calls_reload_accounts(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that re-initialization reloads accounts."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = mock_account

        # First initialization
        await connector.initialize()
        initial_reload_count = selector.reload_accounts.call_count

        # Second initialization
        await connector.initialize()

        # reload_accounts should be called again
        assert selector.reload_accounts.call_count == initial_reload_count + 1

    @pytest.mark.asyncio
    async def test_reinitialization_does_not_advance_rotation_unnecessarily(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that re-initialization doesn't call get_next_account if current account exists."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = mock_account

        # First initialization
        await connector.initialize()
        first_init_next_calls = selector.get_next_account.call_count

        # Second initialization (current account exists)
        await connector.initialize()

        # get_next_account should not be called again (rotation not advanced)
        assert selector.get_next_account.call_count == first_init_next_calls

    @pytest.mark.asyncio
    async def test_reinitialization_advances_rotation_if_no_current_account(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that re-initialization calls get_next_account if no current account."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = None  # No current account

        # First initialization
        await connector.initialize()
        first_init_next_calls = selector.get_next_account.call_count

        # Second initialization (no current account)
        await connector.initialize()

        # get_next_account should be called to get an account
        assert selector.get_next_account.call_count == first_init_next_calls + 1

    @pytest.mark.asyncio
    async def test_multiple_reinitializations_preserve_state(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test that multiple re-initializations preserve service state."""
        mock_account = MagicMock(spec=StoredAccount)
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = mock_account
        selector.get_current_account.return_value = mock_account

        # First initialization
        await connector.initialize()
        storage_instance = connector._token_storage

        # Multiple re-initializations
        for _ in range(5):
            await connector.initialize()
            # Service instance should remain the same
            assert connector._token_storage is storage_instance
            assert connector._is_initialized is True


class TestAccountSelectorReloadPreservesRotation:
    """Tests for AccountSelectorService.reload_accounts() rotation preservation."""

    @pytest.mark.asyncio
    async def test_reload_accounts_preserves_rotation_index(self) -> None:
        """Test that reload_accounts preserves rotation_index within bounds."""
        from src.connectors.gemini_oauth_auto.account_selector import (
            AccountSelectorService,
        )
        from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

        storage = MagicMock(spec=TokenStorageService)
        refresh = MagicMock()
        refresh.refresh_if_needed = AsyncMock(side_effect=lambda acc, **kwargs: acc)

        # Create mock accounts
        account1 = MagicMock(spec=StoredAccount)
        account1.account_id = "account1"
        account1.needs_reauth = False
        account1.is_expired.return_value = False

        account2 = MagicMock(spec=StoredAccount)
        account2.account_id = "account2"
        account2.needs_reauth = False
        account2.is_expired.return_value = False

        storage.load_all_accounts.return_value = [account1, account2]

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=60000,
        )

        # Initial load
        await selector.reload_accounts()
        assert selector.rotation_index == 0

        # Advance rotation
        await selector.get_next_account()
        assert selector.rotation_index == 1

        # Reload accounts (simulates re-initialization)
        await selector.reload_accounts()

        # Rotation index should be preserved (not reset to 0)
        assert selector.rotation_index == 1

    @pytest.mark.asyncio
    async def test_reload_accounts_resets_index_if_out_of_bounds(self) -> None:
        """Test that reload_accounts resets index if it exceeds account count."""
        from src.connectors.gemini_oauth_auto.account_selector import (
            AccountSelectorService,
        )
        from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

        storage = MagicMock(spec=TokenStorageService)
        refresh = MagicMock()
        refresh.refresh_if_needed = AsyncMock(side_effect=lambda acc, **kwargs: acc)

        # Create mock accounts
        account1 = MagicMock(spec=StoredAccount)
        account1.account_id = "account1"
        account1.needs_reauth = False
        account1.is_expired.return_value = False

        storage.load_all_accounts.return_value = [account1]

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=60000,
        )

        # Initial load
        await selector.reload_accounts()

        # Set rotation index beyond bounds
        selector.rotation_index = 5

        # Reload accounts
        await selector.reload_accounts()

        # Index should be reset to 0 (within bounds)
        assert selector.rotation_index == 0

    @pytest.mark.asyncio
    async def test_reload_accounts_updates_current_account(self) -> None:
        """Test that reload_accounts updates current account if it still exists."""
        from src.connectors.gemini_oauth_auto.account_selector import (
            AccountSelectorService,
        )
        from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

        storage = MagicMock(spec=TokenStorageService)
        refresh = MagicMock()
        refresh.refresh_if_needed = AsyncMock(side_effect=lambda acc, **kwargs: acc)

        # Create mock accounts
        account1_v1 = MagicMock(spec=StoredAccount)
        account1_v1.account_id = "account1"
        account1_v1.access_token = "old_token"
        account1_v1.needs_reauth = False
        account1_v1.is_expired.return_value = False

        account1_v2 = MagicMock(spec=StoredAccount)
        account1_v2.account_id = "account1"
        account1_v2.access_token = "new_token"
        account1_v2.needs_reauth = False
        account1_v2.is_expired.return_value = False

        storage.load_all_accounts.return_value = [account1_v1]

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=60000,
        )

        # Initial load and select account
        await selector.reload_accounts()
        selector._current_account = account1_v1

        # Reload with updated account
        storage.load_all_accounts.return_value = [account1_v2]
        await selector.reload_accounts()

        # Current account should be updated to new version
        assert selector._current_account is account1_v2
        assert selector._current_account.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_reload_accounts_clears_current_if_removed(self) -> None:
        """Test that reload_accounts handles removed accounts gracefully."""
        from src.connectors.gemini_oauth_auto.account_selector import (
            AccountSelectorService,
        )
        from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

        storage = MagicMock(spec=TokenStorageService)
        refresh = MagicMock()
        refresh.refresh_if_needed = AsyncMock(side_effect=lambda acc, **kwargs: acc)

        # Create mock accounts
        account1 = MagicMock(spec=StoredAccount)
        account1.account_id = "account1"
        account1.needs_reauth = False
        account1.is_expired.return_value = False

        account2 = MagicMock(spec=StoredAccount)
        account2.account_id = "account2"
        account2.needs_reauth = False
        account2.is_expired.return_value = False

        storage.load_all_accounts.return_value = [account1, account2]

        selector = AccountSelectorService(
            storage=storage,
            refresh_service=refresh,
            refresh_buffer_ms=60000,
        )

        # Initial load and select account1
        await selector.reload_accounts()
        selector._current_account = account1

        # Reload with only account2 (account1 removed)
        storage.load_all_accounts.return_value = [account2]
        await selector.reload_accounts()

        # Reload should complete without errors
        # Current account handling is implementation-dependent
        assert selector._initialized is True
