"""
Integration tests for Gemini OAuth Auto-Connector.

Tests Phase 8: Integration Testing.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.connector import GeminiOAuthAutoConnector
from src.connectors.gemini_oauth_auto.constants import TOKEN_URL
from src.connectors.gemini_oauth_auto.models import StoredAccount
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService
from tests.unit.fixtures.markers import real_time


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=AppConfig)
    config.get.return_value = False

    # Configure backends structure
    backends = MagicMock()
    gemini_config = MagicMock()
    gemini_config.extra = {}

    backends.gemini_oauth_auto = gemini_config
    backends.get.side_effect = lambda key: (
        gemini_config if key in ["gemini-oauth-auto", "gemini_oauth_auto"] else None
    )

    config.backends = backends
    return config


@pytest.fixture
def mock_translation_service() -> MagicMock:
    return MagicMock(spec=TranslationService)


@pytest.mark.integration
@real_time(
    reason="Integration tests use real time for async task scheduling and coordination"
)
class TestGeminiOAuthAutoIntegration:
    """Integration tests for Gemini OAuth Auto-Connector services."""

    @pytest.mark.asyncio
    async def test_service_composition_and_flow(self, tmp_path: Path) -> None:
        """Test the wiring and flow between storage, refresh, and selector."""
        storage = TokenStorageService(storage_path=tmp_path)

        async with httpx.AsyncClient() as client:
            refresh = TokenRefreshService(storage=storage, http_client=client)
            selector = AccountSelectorService(storage=storage, refresh_service=refresh)

            # 1. Start with no accounts
            await selector.reload_accounts()
            assert selector.get_available_count() == 0
            assert await selector.get_next_account() is None

            # 2. Add an account directly to storage
            account = StoredAccount(
                account_id="test-acc-1",
                email="test1@gmail.com",
                access_token="old-token",
                refresh_token="refresh-1",
                scope="scope1",
                expiry_date=int(time.time() * 1000) - 1000,  # Expired
            )
            await storage.save_account(account)

            # 3. Reload and check selector
            await selector.reload_accounts()
            assert selector.get_available_count() == 1

            # 4. Mock Google token endpoint for refresh
            with respx.mock:
                respx.post(TOKEN_URL).mock(
                    return_value=httpx.Response(
                        200,
                        json={
                            "access_token": "new-token-1",
                            "expires_in": 3600,
                            "token_type": "Bearer",
                        },
                    )
                )

                # 5. Get next account should trigger refresh
                selected = await selector.get_next_account()

                assert selected is not None
                assert selected.account_id == "test-acc-1"
                assert selected.access_token == "new-token-1"
                assert not selected.is_expired()

                # 6. Verify storage was updated
                stored = await storage.get_account("test-acc-1")
                assert stored is not None
                assert stored.access_token == "new-token-1"

    @pytest.mark.asyncio
    async def test_connector_initialization_and_rotation(
        self,
        tmp_path: Path,
        mock_config: MagicMock,
        mock_translation_service: MagicMock,
    ) -> None:
        """Test connector initialization and account rotation."""
        # Setup storage with two accounts
        storage_path = tmp_path / "accounts"
        storage_path.mkdir()

        acc1 = StoredAccount(
            account_id="acc-1",
            email="acc1@gmail.com",
            access_token="token-1",
            refresh_token="ref-1",
            scope="s",
            expiry_date=int(time.time() * 1000) + 3600000,
        )
        acc2 = StoredAccount(
            account_id="acc-2",
            email="acc2@gmail.com",
            access_token="token-2",
            refresh_token="ref-2",
            scope="s",
            expiry_date=int(time.time() * 1000) + 3600000,
        )

        # Write files manually to simulate existing storage
        (storage_path / "acc-1.json").write_text(acc1.model_dump_json())
        (storage_path / "acc-2.json").write_text(acc2.model_dump_json())

        async with httpx.AsyncClient() as client:
            mock_config.backends.get("gemini-oauth-auto").extra["storage_path"] = str(
                storage_path
            )

            connector = GeminiOAuthAutoConnector(
                client=client,
                config=mock_config,
                translation_service=mock_translation_service,
            )

            connector._ensure_models_loaded = AsyncMock()

            await connector.initialize()

            assert connector.is_functional is True
            assert connector.is_backend_functional() is True

            # Check current credentials (should be acc-1 because initialize calls get_next_account)
            creds = connector._oauth_credentials
            assert creds is not None
            assert creds["access_token"] == "token-1"

            # Trigger rotation via quota exhaustion
            # Note: _mark_backend_unusable schedules a task
            connector._mark_backend_unusable(reason="quota_exceeded")

            # Give it a moment to rotate
            await asyncio.sleep(0.1)

            # Now should be acc-2
            creds = connector._oauth_credentials
            assert creds is not None
            assert creds["access_token"] == "token-2"

            # Rotate again (back to acc-1 in round-robin)
            connector._mark_backend_unusable(reason="quota_exceeded")
            await asyncio.sleep(0.1)

            creds = connector._oauth_credentials
            assert creds is not None
            assert creds["access_token"] == "token-1"
