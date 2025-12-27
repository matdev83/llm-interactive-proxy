"""
Tests for Gemini OAuth Free connector.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.gemini_oauth_free import GeminiOAuthFreeConnector


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a GeminiOAuthFreeConnector instance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return GeminiOAuthFreeConnector(
        mock_client, config, translation_service, name="gemini-oauth-free"
    )


class TestGeminiOAuthFreeConnector:
    """Test cases for GeminiOAuthFreeConnector."""

    def test_backend_type(self, connector):
        """Test that the backend type is correct."""
        assert connector.backend_type == "gemini-oauth-free"

    def test_initialization(self, connector):
        """Test that the connector initializes with correct default values."""
        assert connector.name == "gemini-oauth-free"
        assert connector._oauth_credentials is None
        assert connector._credentials_path is None
        assert connector._last_modified == 0
        # Token manager state accessed through composed object
        assert connector._token_manager._refresh_token is None
        assert isinstance(connector._token_manager._token_refresh_lock, asyncio.Lock)
        assert connector._token_manager._last_cli_refresh_attempt == 0.0
        assert connector._token_manager._cli_refresh_process is None

    @patch("asyncio.to_thread")
    async def test_discover_project_id_for_free_tier(self, mock_to_thread, connector):
        """Test that the project ID is discovered correctly for the free tier."""
        connector.gemini_api_base_url = "https://example.com"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"cloudaicompanionProject": "test-project-id"}

        mock_auth_session = MagicMock()
        mock_auth_session.request.return_value = mock_response

        async def to_thread_side_effect(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_to_thread.side_effect = to_thread_side_effect

        project_id = await connector._discover_project_id(mock_auth_session)

        assert project_id == "test-project-id"
        assert connector._project_id == "test-project-id"
        mock_to_thread.assert_called_once()

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_refresh_token_waits_for_delayed_cli_update(
        self, connector, monkeypatch
    ):
        """Ensure refresh waits for credentials file update instead of failing fast."""
        from src.connectors.gemini_base.models import GeminiOAuthCredentials
        from tests.utils.fake_clock import FakeClock, FakeClockContext

        async with FakeClockContext(FakeClock(initial_time=1704067200.0)) as clock:
            # Set initial credentials in coordinator (which is the source of truth after refactoring)
            initial_creds = GeminiOAuthCredentials(
                access_token="initial-token",
                refresh_token="refresh-token",
                expiry_date=int((clock.now() - 120) * 1000),
            )
            connector._credential_coordinator._credentials = initial_creds
            # Also set in connector for backward compatibility
            connector._oauth_credentials = initial_creds.to_dict()

            monkeypatch.setattr(
                connector,
                "_should_trigger_cli_refresh",
                MagicMock(return_value=False),
            )
            monkeypatch.setattr(connector, "_launch_cli_refresh_process", MagicMock())

            load_calls = 0

            async def fake_load_internal(
                force_reload: bool = False, silent: bool = False
            ) -> bool:
                nonlocal load_calls
                load_calls += 1
                if load_calls >= 7:
                    # Update coordinator's credentials (which syncs to connector via property)
                    updated_creds = GeminiOAuthCredentials(
                        access_token=f"new-token-{load_calls}",
                        refresh_token="refresh-token",
                        expiry_date=int((clock.now() + 3600) * 1000),
                    )
                    connector._credential_coordinator._credentials = updated_creds
                return True

            # Mock the coordinator's internal method (actual code path after refactoring)
            connector._credential_coordinator._load_credentials_internal = AsyncMock(  # type: ignore[assignment]
                side_effect=fake_load_internal
            )

            sleep_calls = 0

            async def fake_sleep(_: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1

            monkeypatch.setattr(asyncio, "sleep", fake_sleep)

            result = await connector._refresh_token_if_needed()

            assert result is True
            assert sleep_calls >= 6
            assert connector._oauth_credentials["access_token"].startswith("new-token")
