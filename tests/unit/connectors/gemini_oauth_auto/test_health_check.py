"""
Unit tests for GeminiOAuthAutoConnector health and functional state.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector


@pytest.fixture
def mock_dependencies():
    """Fixture providing common mocks for the connector."""
    client = MagicMock(spec=httpx.AsyncClient)
    config = MagicMock()
    # Mock config.get to return False for disable_health_checks
    config.get.return_value = False
    translation_service = MagicMock()
    return client, config, translation_service


@pytest.fixture
async def connector(mock_dependencies, mocker):
    """Fixture providing an initialized GeminiOAuthAutoConnector."""
    client, config, translation_service = mock_dependencies

    # Configure mock selector
    mock_selector = MagicMock()
    mock_selector.reload_accounts = AsyncMock()
    mock_selector.get_next_account = AsyncMock()
    mock_selector.get_available_count.return_value = 1

    # Patch services in the connector module
    mocker.patch("src.connectors.gemini_oauth_auto.connector.TokenStorageService")
    mocker.patch("src.connectors.gemini_oauth_auto.connector.TokenRefreshService")
    mocker.patch(
        "src.connectors.gemini_oauth_auto.connector.AccountSelectorService",
        return_value=mock_selector,
    )

    conn = GeminiOAuthAutoConnector(client, config, translation_service)
    # Ensure it uses the mock even before initialize
    conn._account_selector = mock_selector

    return conn


@pytest.mark.asyncio
class TestGeminiOAuthAutoHealth:
    """Tests for health and functional status of GeminiOAuthAutoConnector."""

    async def test_initialize_sets_api_url(self, connector):
        """Test that initialization sets the base api_url for health checks."""
        await connector.initialize(gemini_api_base_url="https://custom.api.com")
        assert connector.api_url == "https://custom.api.com"

    async def test_is_backend_functional_combined_logic(self, connector):
        """Test is_backend_functional combines base logic and account count."""
        await connector.initialize()

        # 1. Healthy state
        connector.is_functional = True
        connector._account_selector.get_available_count.return_value = 2
        connector._endpoint_healthy = True
        connector._auth_valid = True
        assert connector.is_backend_functional() is True

        # 2. No accounts -> Unfunctional
        connector._account_selector.get_available_count.return_value = 0
        assert connector.is_backend_functional() is False

        # 3. Endpoint unhealthy -> Unfunctional
        connector._account_selector.get_available_count.return_value = 2
        connector._endpoint_healthy = False
        assert connector.is_backend_functional() is False

        # 4. Auth invalid -> Unfunctional
        connector._endpoint_healthy = True
        connector._auth_valid = False
        assert connector.is_backend_functional() is False

    async def test_get_validation_errors_includes_account_info(self, connector):
        """Test get_validation_errors reports missing accounts."""
        await connector.initialize()

        # Scenario: No accounts
        connector._account_selector.get_available_count.return_value = 0
        errors = connector.get_validation_errors()
        assert any("No valid OAuth accounts" in e for e in errors)

        # Scenario: Endpoint unhealthy
        connector._account_selector.get_available_count.return_value = 1
        connector._endpoint_healthy = False
        connector._last_health_change_reason = "Connection refused"
        errors = connector.get_validation_errors()
        assert any("API endpoint unhealthy: Connection refused" in e for e in errors)

        # Scenario: All good
        connector._endpoint_healthy = True
        connector._last_health_change_reason = None
        errors = connector.get_validation_errors()
        assert len(errors) == 0
