"""
Unit tests for Kiro OAuthFlowService.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from freezegun import freeze_time
from src.connectors.kiro_oauth_auto.errors import OAuthError
from src.connectors.kiro_oauth_auto.oauth_flow import OAuthFlowService


@pytest.fixture
def mock_http_client() -> MagicMock:
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def flow(mock_http_client: MagicMock) -> OAuthFlowService:
    return OAuthFlowService(http_client=mock_http_client)


@freeze_time("2026-01-19")
class TestOAuthFlowService:
    @pytest.mark.asyncio
    async def test_register_oidc_client_success(
        self, flow: OAuthFlowService, mock_http_client: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"clientId": "cid", "clientSecret": "csec"}
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        client_id, client_secret = await flow.register_oidc_client(region="us-east-1")
        assert client_id == "cid"
        assert client_secret == "csec"

    @pytest.mark.asyncio
    async def test_register_oidc_client_failure_raises(
        self, flow: OAuthFlowService, mock_http_client: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad"
        mock_http_client.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(OAuthError):
            await flow.register_oidc_client(region="us-east-1")

    @pytest.mark.asyncio
    async def test_start_device_authorization_success(
        self, flow: OAuthFlowService, mock_http_client: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "deviceCode": "dc",
            "userCode": "uc",
            "verificationUri": "https://example.test",
            "verificationUriComplete": "https://example.test/?user_code=uc",
            "interval": 5,
            "expiresIn": 600,
        }
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        device = await flow.start_device_authorization(
            client_id="cid",
            client_secret="csec",
            region="us-east-1",
        )
        assert device.device_code == "dc"
        assert device.user_code == "uc"
        assert device.verification_uri.startswith("https://")

    @pytest.mark.asyncio
    async def test_poll_for_token_pending_then_success(
        self, flow: OAuthFlowService, mock_http_client: MagicMock
    ) -> None:
        pending = MagicMock()
        pending.status_code = 400
        pending.json.return_value = {"error": "authorization_pending"}

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "accessToken": "atok",
            "refreshToken": "rtok",
            "expiresIn": 3600,
        }
        mock_http_client.post = AsyncMock(side_effect=[pending, success])

        with patch(
            "src.connectors.kiro_oauth_auto.oauth_flow.asyncio_sleep",
            new_callable=AsyncMock,
        ):
            access, refresh, expires_in = await flow.poll_for_token(
                client_id="cid",
                client_secret="csec",
                device_code="dc",
                region="us-east-1",
                poll_interval_seconds=1,
                timeout_seconds=3,
            )
        assert access == "atok"
        assert refresh == "rtok"
        assert expires_in == 3600

    @pytest.mark.asyncio
    async def test_poll_for_token_unexpected_error_raises(
        self, flow: OAuthFlowService, mock_http_client: MagicMock
    ) -> None:
        resp = MagicMock()
        resp.status_code = 400
        resp.json.return_value = {"error": "access_denied"}
        mock_http_client.post = AsyncMock(return_value=resp)

        with (
            patch(
                "src.connectors.kiro_oauth_auto.oauth_flow.asyncio_sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(OAuthError),
        ):
            await flow.poll_for_token(
                client_id="cid",
                client_secret="csec",
                device_code="dc",
                region="us-east-1",
                poll_interval_seconds=1,
                timeout_seconds=2,
            )
