"""Regression tests for ManagedOAuthRefreshService (token POST + retries)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_refresh import (
    ManagedOAuthRefreshError,
    ManagedOAuthRefreshService,
)
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


def _expired_account() -> ManagedOAuthAccount:
    return ManagedOAuthAccount(
        account_id="acc1",
        access_token="old_access",
        refresh_token="refresh_tok",
        expiry_date=int(time.time() * 1000) - 3_600_000,
    )


@pytest.mark.asyncio
async def test_force_refresh_retries_transient_read_timeout_then_succeeds(
    tmp_path,
) -> None:
    """ReadTimeout on token POST should retry (parity with legacy OAuth refresh)."""
    storage = ManagedOAuthStorageService(tmp_path)
    account = _expired_account()
    await storage.save_account(account)

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "refresh_tok",
        "expires_in": 3600,
    }

    client = Mock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        side_effect=[httpx.ReadTimeout("read timeout"), mock_response],
    )

    svc = ManagedOAuthRefreshService(storage, http_client=client, max_retries=3)
    with patch(
        "src.connectors.openai_codex.managed_oauth_refresh.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        updated = await svc.force_refresh(account)

    assert updated.access_token == "new_access"
    assert client.post.await_count == 2


@pytest.mark.asyncio
async def test_force_refresh_exhausts_retries_on_transient_errors_sets_flag(
    tmp_path,
) -> None:
    """After max retries, ManagedOAuthRefreshError carries transient-network flag."""
    storage = ManagedOAuthStorageService(tmp_path)
    account = _expired_account()
    await storage.save_account(account)

    client = Mock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=httpx.ReadTimeout("read timeout"))

    svc = ManagedOAuthRefreshService(storage, http_client=client, max_retries=3)
    with (
        patch(
            "src.connectors.openai_codex.managed_oauth_refresh.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        pytest.raises(ManagedOAuthRefreshError) as ctx,
    ):
        await svc.force_refresh(account)

    assert ctx.value.from_transient_network is True
    assert client.post.await_count == 3


@pytest.mark.asyncio
async def test_force_refresh_non_transient_failure_sets_transient_flag_false(
    tmp_path,
) -> None:
    """Non-network errors are not flagged as transient (upstream may log with exc_info)."""
    storage = ManagedOAuthStorageService(tmp_path)
    account = _expired_account()
    await storage.save_account(account)

    client = Mock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=OSError("unexpected"))

    svc = ManagedOAuthRefreshService(storage, http_client=client, max_retries=1)
    with pytest.raises(ManagedOAuthRefreshError) as ctx:
        await svc.force_refresh(account)

    assert ctx.value.from_transient_network is False
