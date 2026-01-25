"""
Unit tests for GeminiOAuthAutoConnector.

Tests Requirement 9: Connector implementation.
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
    # Patch services during init and initialization
    with patch(
        "src.connectors.gemini_oauth_auto.connector.TokenStorageService"
    ), patch(
        "src.connectors.gemini_oauth_auto.connector.TokenRefreshService"
    ), patch(
        "src.connectors.gemini_oauth_auto.connector.AccountSelectorService"
    ) as mock_selector_cls:
        # Configure mock selector to be returned by constructor
        mock_selector = mock_selector_cls.return_value
        mock_selector.reload_accounts = AsyncMock()
        mock_selector.get_next_account = AsyncMock()
        mock_selector.get_current_account = MagicMock()
        mock_selector.get_available_count = MagicMock(return_value=0)
        mock_selector.rotate_on_quota = AsyncMock()

        conn = GeminiOAuthAutoConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )
        
        # Inject the mock manually too for pre-initialization state
        conn._account_selector = mock_selector
        
        # Mock base class methods we don't want to run in unit tests
        conn._ensure_models_loaded = AsyncMock()
        
        yield conn


class TestGeminiOAuthAutoConnector:
    """Tests for GeminiOAuthAutoConnector."""

    @pytest.mark.asyncio
    async def test_initialize_loads_accounts(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize() calls reload_accounts and get_next_account."""
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = MagicMock(spec=StoredAccount)
        
        await connector.initialize()
        
        selector.reload_accounts.assert_called_once()
        selector.get_next_account.assert_called_once()
        assert connector.is_functional is True

    @pytest.mark.asyncio
    async def test_initialize_no_accounts_sets_functional_false(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize() with no accounts sets functional state to False."""
        selector = cast(MagicMock, connector._account_selector)
        selector.get_next_account.return_value = None
        
        await connector.initialize()
        
        assert connector.is_functional is False

    def test_oauth_credentials_property(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _oauth_credentials property delegates to account selector."""
        selector = cast(MagicMock, connector._account_selector)
        mock_account = MagicMock(spec=StoredAccount)
        mock_account.to_credentials_dict.return_value = {"access_token": "test_token"}
        selector.get_current_account.return_value = mock_account
        
        creds = connector._oauth_credentials
        
        assert creds == {"access_token": "test_token"}
        selector.get_current_account.assert_called_once()

    def test_oauth_credentials_property_none(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _oauth_credentials property returns None if no account selected."""
        selector = cast(MagicMock, connector._account_selector)
        selector.get_current_account.return_value = None
        
        assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_delegates(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _refresh_token_if_needed() calls get_next_account if current expired."""
        selector = cast(MagicMock, connector._account_selector)
        mock_account = MagicMock(spec=StoredAccount)
        mock_account.is_expired.return_value = True
        selector.get_current_account.return_value = mock_account
        selector.get_next_account.return_value = mock_account
        
        result = await connector._refresh_token_if_needed()
        
        assert result is True
        selector.get_next_account.assert_called_once()

    def test_is_backend_functional_checks_count(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test is_backend_functional() checks available account count."""
        selector = cast(MagicMock, connector._account_selector)
        connector.is_functional = True
        selector.get_available_count.return_value = 5
        
        assert connector.is_backend_functional() is True
        
        selector.get_available_count.return_value = 0
        assert connector.is_backend_functional() is False

    def test_parse_accounts_allowlist(self) -> None:
        """Test parsing of accounts allowlist from various formats."""
        # String 'all'
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist("all") is None
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist("ALL") is None
        
        # Comma-separated string
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist("a, b, c") == {"a", "b", "c"}
        
        # List
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist(["a", "b"]) == {"a", "b"}
        
        # None or empty
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist(None) is None
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist("") is None
        assert GeminiOAuthAutoConnector._parse_accounts_allowlist([]) is None

    @pytest.mark.asyncio
    async def test_initialize_config_error_uses_defaults(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize handles invalid config by falling back to defaults."""
        mock_backend_settings = MagicMock()
        mock_backend_settings.get.return_value = MagicMock(extra={"refresh_buffer_seconds": "invalid"})
        connector.config.backends = mock_backend_settings
        
        # Should not raise exception
        await connector.initialize()
        assert connector._account_selector is not None

    @pytest.mark.asyncio
    async def test_initialize_debug_override_flags(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test initialize correctly sets debug override flag from various sources."""
        # 1. From kwargs
        await connector.initialize(enable_gemini_oauth_auto_backend_debugging_override=True)
        assert connector._enable_gemini_oauth_auto_backend_debugging_override is True
        
        await connector.initialize(enable_gemini_oauth_auto_backend_debugging_override=False)
        assert connector._enable_gemini_oauth_auto_backend_debugging_override is False

    def test_sync_selected_account_to_base_no_coordinator(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test sync_selected_account_to_base handles missing coordinator."""
        # Ensure it doesn't exist
        if hasattr(connector, "_credential_coordinator"):
            delattr(connector, "_credential_coordinator")
        
        # Should not raise
        connector._sync_selected_account_to_base()

    def test_sync_selected_account_to_base_exception_logged(
        self, connector: GeminiOAuthAutoConnector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test sync_selected_account_to_base logs exception on failure."""
        connector._credential_coordinator = MagicMock()
        mock_account = MagicMock()
        mock_account.to_credentials_dict.side_effect = Exception("Sync failed")
        selector = cast(MagicMock, connector._account_selector)
        selector.get_current_account.return_value = mock_account
        
        connector._sync_selected_account_to_base()
        
        assert "Failed to sync" in caplog.text

    @pytest.mark.asyncio
    async def test_refresh_token_force_reload(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test _refresh_token_if_needed(force_reload=True) calls reload_accounts."""
        selector = cast(MagicMock, connector._account_selector)
        selector.reload_accounts = AsyncMock()
        await connector._refresh_token_if_needed(force_reload=True)
        selector.reload_accounts.assert_called_once()

    def test_get_validation_errors_branches(
        self, connector: GeminiOAuthAutoConnector
    ) -> None:
        """Test get_validation_errors returns various error types."""
        selector = cast(MagicMock, connector._account_selector)
        connector.is_functional = True
        connector._auth_valid = False
        connector._last_health_change_reason = "Expired"
        selector.get_available_count.return_value = 1
        
        errors = connector.get_validation_errors()
        assert any("Credentials invalid: Expired" in e for e in errors)
        
        connector._auth_valid = True
        connector._endpoint_healthy = False
        connector._last_health_change_reason = "Timeout"
        errors = connector.get_validation_errors()
        assert any("API endpoint unhealthy: Timeout" in e for e in errors)
        
        connector._endpoint_healthy = True
        selector.get_available_count.return_value = 0
        errors = connector.get_validation_errors()
        assert any("No valid OAuth accounts" in e for e in errors)
        
        selector.get_available_count.return_value = 1
        connector.is_functional = False
        errors = connector.get_validation_errors()
        assert any("initialization failed" in e for e in errors)

