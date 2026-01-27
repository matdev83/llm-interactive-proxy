"""
Unit tests for Kiro TokenRefreshService.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from freezegun import freeze_time
from src.connectors.kiro_oauth_auto.errors import TokenRefreshError
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_refresh import TokenRefreshService

# Matches @freeze_time("2026-01-19")
BASE_TIME = 1768780800.0  # 2026-01-19 00:00:00 UTC


@pytest.fixture
def mock_storage() -> MagicMock:
    storage = MagicMock()
    storage.save_account = AsyncMock()
    return storage


@pytest.fixture
def mock_http_client() -> MagicMock:
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def refresh_service(
    mock_storage: MagicMock, mock_http_client: MagicMock
) -> TokenRefreshService:
    return TokenRefreshService(storage=mock_storage, http_client=mock_http_client)


@pytest.fixture
def expired_account() -> StoredAccount:
    return StoredAccount(
        account_id="test-account",
        auth_method="builderid",
        region="us-east-1",
        access_token="access.old",
        refresh_token="refresh.test",
        client_id="client.test",
        client_secret="secret.test",
        expiry_date=int((BASE_TIME - 10) * 1000),
    )


@freeze_time("2026-01-19")
class TestTokenRefreshService:
    @pytest.mark.asyncio
    async def test_refresh_success_updates_and_persists(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "accessToken": "access.new",
            "refreshToken": "refresh.new",
            "expiresIn": 3600,
        }
        mock_http_client.post = AsyncMock(return_value=mock_response)

        updated = await refresh_service.refresh_account(expired_account)

        assert updated.access_token == "access.new"
        assert updated.refresh_token == "refresh.new"
        mock_storage.save_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_http_error_raises(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "nope"
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(TokenRefreshError):
            await refresh_service.refresh_account(expired_account)

    @pytest.mark.asyncio
    async def test_refresh_network_error_raises(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        mock_http_client.post = AsyncMock(side_effect=httpx.RequestError("boom"))
        with pytest.raises(TokenRefreshError):
            await refresh_service.refresh_account(expired_account)
