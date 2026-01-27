"""Token refresh for Kiro OAuth auto-connector."""

from __future__ import annotations

import logging
import time

import httpx

from src.connectors.kiro_oauth_auto.errors import TokenRefreshError
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService

logger = logging.getLogger(__name__)


class TokenRefreshService:
    """Refreshes access tokens using OIDC refresh_token flow."""

    def __init__(
        self, *, storage: TokenStorageService, http_client: httpx.AsyncClient
    ) -> None:
        self._storage = storage
        self._http = http_client

    async def refresh_account(self, account: StoredAccount) -> StoredAccount:
        url = f"https://oidc.{account.region}.amazonaws.com/token"
        payload = {
            "clientId": account.client_id,
            "clientSecret": account.client_secret,
            "refreshToken": account.refresh_token,
            "grantType": "refresh_token",
        }

        try:
            res = await self._http.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            )
        except httpx.RequestError as exc:
            raise TokenRefreshError(f"Token refresh request failed: {exc}") from exc

        if res.status_code != 200:
            body = res.text[:2000]
            raise TokenRefreshError(
                f"Token refresh failed: HTTP {res.status_code}: {body}"
            )

        data = res.json()
        access_token = data.get("accessToken")
        expires_in = data.get("expiresIn")
        refresh_token = data.get("refreshToken") or None

        if not isinstance(access_token, str) or not access_token:
            raise TokenRefreshError("Token refresh response missing accessToken")
        if not isinstance(expires_in, int | float):
            raise TokenRefreshError("Token refresh response missing expiresIn")

        expiry_date_ms = int((time.time() + float(expires_in)) * 1000)
        updated = account.with_updated_tokens(
            access_token=access_token,
            expiry_date=expiry_date_ms,
            refresh_token=refresh_token,
        )
        await self._storage.save_account(updated)
        return updated
