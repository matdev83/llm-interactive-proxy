"""
Unit tests for GeminiOAuthAutoConnector.

Tests Requirement 9: Connector implementation.
"""

import asyncio
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
) -> GeminiOAuthAutoConnector:
    """Fixture providing GeminiOAuthAutoConnector with mocked dependencies."""
    # Patch services during init
    with patch(
        "src.connectors.gemini_oauth_auto.connector.TokenStorageService"
    ), patch(
        "src.connectors.gemini_oauth_auto.connector.TokenRefreshService"
    ), patch(
        "src.connectors.gemini_oauth_auto.connector.AccountSelectorService"
    ):
        conn = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )
        # Mock the internal services
        conn._token_storage = MagicMock()
        conn._token_refresh = MagicMock()
        conn._account_selector = MagicMock()
        conn._account_selector.reload_accounts = AsyncMock()
        conn._account_selector.get_next_account = AsyncMock()
        conn._account_selector.get_current_account = MagicMock()
        conn._account_selector.get_available_count = MagicMock(return_value=0)
        conn._account_selector.rotate_on_quota = AsyncMock()
        
        # Mock base class methods we don't want to run in unit tests
        conn._ensure_models_loaded = AsyncMock()
        
        return conn


class TestGeminiOAuthAutoConnector:
    """Tests for GeminiOAuthAutoConnector."""

    @pytest.mark.asyncio
    async def test_initialize_loads_accounts(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize() calls reload_accounts and get_next_account."""
        connector._account_selector.get_next_account.return_value = MagicMock(spec=StoredAccount)
        
        await connector.initialize()
        
        connector._account_selector.reload_accounts.assert_called_once()
        connector._account_selector.get_next_account.assert_called_once()
        assert connector.is_functional is True

    @pytest.mark.asyncio
    async def test_initialize_no_accounts_sets_functional_false(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize() with no accounts sets functional state to False."""
        connector._account_selector.get_next_account.return_value = None
        
        await connector.initialize()
        
        assert connector.is_functional is False

    def test_oauth_credentials_property(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _oauth_credentials property delegates to account selector."""
        mock_account = MagicMock(spec=StoredAccount)
        mock_account.to_credentials_dict.return_value = {"access_token": "test_token"}
        connector._account_selector.get_current_account.return_value = mock_account
        
        creds = connector._oauth_credentials
        
        assert creds == {"access_token": "test_token"}
        connector._account_selector.get_current_account.assert_called_once()

    def test_oauth_credentials_property_none(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _oauth_credentials property returns None if no account selected."""
        connector._account_selector.get_current_account.return_value = None
        
        assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_delegates(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _refresh_token_if_needed() calls get_next_account if current expired."""
        mock_account = MagicMock(spec=StoredAccount)
        mock_account.is_expired.return_value = True
        connector._account_selector.get_current_account.return_value = mock_account
        connector._account_selector.get_next_account.return_value = mock_account
        
        result = await connector._refresh_token_if_needed()
        
        assert result is True
        connector._account_selector.get_next_account.assert_called_once()

    def test_is_backend_functional_checks_count(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test is_backend_functional() checks available account count."""
        connector.is_functional = True
        connector._account_selector.get_available_count.return_value = 5
        
        assert connector.is_backend_functional() is True
        
        connector._account_selector.get_available_count.return_value = 0
        assert connector.is_backend_functional() is False

    @pytest.mark.asyncio
    async def test_mark_unusable_quota_rotates(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _mark_backend_unusable(quota_exceeded) triggers rotation."""
        connector._account_selector.rotate_on_quota = AsyncMock()

        connector._mark_backend_unusable(reason="quota_exceeded")

        # Give event loop a chance to run the task
        await asyncio.sleep(0.01)

        connector._account_selector.rotate_on_quota.assert_called_once()
