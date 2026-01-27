"""OAuth flow helpers for Kiro OAuth auto-connector."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from src.connectors.kiro_oauth_auto.constants import (
    DEFAULT_OIDC_SCOPES,
    DEFAULT_REGION,
    DEFAULT_START_URL,
)
from src.connectors.kiro_oauth_auto.errors import OAuthError
from src.connectors.kiro_oauth_auto.models import StoredAccount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceAuthorizationInfo:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval_seconds: int
    expires_in_seconds: int


class OAuthFlowService:
    """Implements Builder ID device-code login via AWS OIDC endpoints."""

    def __init__(self, *, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def register_oidc_client(
        self,
        *,
        region: str = DEFAULT_REGION,
        start_url: str = DEFAULT_START_URL,
        scopes: tuple[str, ...] = DEFAULT_OIDC_SCOPES,
        client_name: str = "llm-interactive-proxy",
    ) -> tuple[str, str]:
        oidc_base = f"https://oidc.{region}.amazonaws.com"
        res = await self._http.post(
            f"{oidc_base}/client/register",
            json={
                "clientName": client_name,
                "clientType": "public",
                "scopes": list(scopes),
                "grantTypes": [
                    "urn:ietf:params:oauth:grant-type:device_code",
                    "refresh_token",
                ],
                "issuerUrl": start_url,
            },
            headers={"Content-Type": "application/json"},
        )
        if res.status_code != 200:
            raise OAuthError(
                f"OIDC client registration failed: HTTP {res.status_code}: {res.text[:2000]}"
            )

        data = res.json()
        client_id = data.get("clientId")
        client_secret = data.get("clientSecret")
        if not isinstance(client_id, str) or not client_id:
            raise OAuthError("OIDC client registration response missing clientId")
        if not isinstance(client_secret, str) or not client_secret:
            raise OAuthError("OIDC client registration response missing clientSecret")
        return client_id, client_secret

    async def start_device_authorization(
        self,
        *,
        client_id: str,
        client_secret: str,
        region: str = DEFAULT_REGION,
        start_url: str = DEFAULT_START_URL,
    ) -> DeviceAuthorizationInfo:
        oidc_base = f"https://oidc.{region}.amazonaws.com"
        res = await self._http.post(
            f"{oidc_base}/device_authorization",
            json={
                "clientId": client_id,
                "clientSecret": client_secret,
                "startUrl": start_url,
            },
            headers={"Content-Type": "application/json"},
        )
        if res.status_code != 200:
            raise OAuthError(
                f"Device authorization failed: HTTP {res.status_code}: {res.text[:2000]}"
            )
        data = res.json()
        device_code = data.get("deviceCode")
        user_code = data.get("userCode")
        verification_uri = data.get("verificationUri")
        verification_uri_complete = data.get("verificationUriComplete")
        interval = data.get("interval", 5)
        expires_in = data.get("expiresIn", 600)

        if not isinstance(device_code, str) or not device_code:
            raise OAuthError("Device authorization response missing deviceCode")
        if not isinstance(user_code, str) or not user_code:
            raise OAuthError("Device authorization response missing userCode")
        if not isinstance(verification_uri, str) or not verification_uri:
            raise OAuthError("Device authorization response missing verificationUri")

        if not isinstance(interval, int):
            interval = 5
        if not isinstance(expires_in, int):
            expires_in = 600

        return DeviceAuthorizationInfo(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=(
                verification_uri_complete
                if isinstance(verification_uri_complete, str)
                else None
            ),
            interval_seconds=max(1, interval),
            expires_in_seconds=max(1, expires_in),
        )

    async def poll_for_token(
        self,
        *,
        client_id: str,
        client_secret: str,
        device_code: str,
        region: str = DEFAULT_REGION,
        poll_interval_seconds: int = 5,
        timeout_seconds: int = 180,
    ) -> tuple[str, str, int]:
        oidc_base = f"https://oidc.{region}.amazonaws.com"
        start = time.time()
        interval = max(1, poll_interval_seconds)

        while (time.time() - start) < timeout_seconds:
            await asyncio_sleep(interval)
            res = await self._http.post(
                f"{oidc_base}/token",
                json={
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "grantType": "urn:ietf:params:oauth:grant-type:device_code",
                    "deviceCode": device_code,
                },
                headers={"Content-Type": "application/json"},
            )

            if res.status_code == 200:
                data = res.json()
                access_token = data.get("accessToken")
                refresh_token = data.get("refreshToken")
                expires_in = data.get("expiresIn", 3600)
                if not isinstance(access_token, str) or not access_token:
                    raise OAuthError("Token response missing accessToken")
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise OAuthError("Token response missing refreshToken")
                if not isinstance(expires_in, int | float):
                    expires_in = 3600
                return access_token, refresh_token, int(float(expires_in))

            if res.status_code == 400:
                data = res.json()
                error = data.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                if error == "expired_token":
                    raise OAuthError("Device code expired")
                if error == "access_denied":
                    raise OAuthError("Access denied by user")
                raise OAuthError(f"Token polling failed: {error}")

            raise OAuthError(
                f"Token polling failed: HTTP {res.status_code}: {res.text[:2000]}"
            )

        raise OAuthError("Authorization timed out")

    async def complete_builder_id_device_flow(
        self,
        *,
        account_id: str,
        region: str = DEFAULT_REGION,
        start_url: str = DEFAULT_START_URL,
        scopes: tuple[str, ...] = DEFAULT_OIDC_SCOPES,
    ) -> tuple[DeviceAuthorizationInfo, StoredAccount]:
        client_id, client_secret = await self.register_oidc_client(
            region=region, start_url=start_url, scopes=scopes
        )
        device = await self.start_device_authorization(
            client_id=client_id,
            client_secret=client_secret,
            region=region,
            start_url=start_url,
        )
        access_token, refresh_token, expires_in = await self.poll_for_token(
            client_id=client_id,
            client_secret=client_secret,
            device_code=device.device_code,
            region=region,
            poll_interval_seconds=device.interval_seconds,
            timeout_seconds=device.expires_in_seconds,
        )
        expiry_ms = int((time.time() + expires_in) * 1000)
        account = StoredAccount(
            account_id=account_id,
            auth_method="builderid",
            region=region,
            access_token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            expiry_date=expiry_ms,
        )
        return device, account


async def asyncio_sleep(seconds: int) -> None:
    # small indirection to simplify unit testing
    import asyncio

    await asyncio.sleep(seconds)
