from unittest.mock import MagicMock, patch

import httpx
import pytest
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector


@pytest.fixture
def mock_dependencies():
    client = MagicMock(spec=httpx.AsyncClient)
    config = MagicMock()
    config.get.return_value = False
    translation_service = MagicMock()
    return client, config, translation_service


@pytest.fixture
async def connector(mock_dependencies):
    client, config, translation_service = mock_dependencies

    with (
        patch("src.connectors.gemini_oauth_auto.connector.TokenStorageService"),
        patch("src.connectors.gemini_oauth_auto.connector.TokenRefreshService"),
        patch(
            "src.connectors.gemini_oauth_auto.connector.AccountSelectorService"
        ) as mock_selector_cls,
    ):
        from unittest.mock import AsyncMock

        mock_selector = mock_selector_cls.return_value
        mock_selector.reload_accounts = AsyncMock()
        mock_selector.get_next_account = AsyncMock()
        mock_selector.get_available_count.return_value = 1

        conn = GeminiOAuthAutoConnector(client, config, translation_service)
        # In initialize, it will create a new one, but we want to see it's a mock
        yield conn


@pytest.mark.asyncio
async def test_check_type(connector):
    print(
        f"\nType of _account_selector before init: {type(connector._account_selector)}"
    )
    await connector.initialize()
    print(f"Type of _account_selector after init: {type(connector._account_selector)}")

    # This matches exactly what's in the failing test
    connector._account_selector.get_available_count.return_value = 2
    print(f"Value: {connector._account_selector.get_available_count()}")
    assert connector._account_selector.get_available_count() == 2
