from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.gemini_oauth_auto.account_selector import AccountSelectorService
from src.connectors.gemini_oauth_auto.models import StoredAccount


@pytest.mark.asyncio
async def test_mark_current_account_blocked_sends_verification_notification() -> None:
    storage = MagicMock()
    refresh = MagicMock()

    notification_service = MagicMock()
    notification_service.is_enabled = True
    notification_service.send_notification = AsyncMock(return_value="id")

    selector = AccountSelectorService(
        storage=storage,
        refresh_service=refresh,
        notification_service=notification_service,
    )

    selector._accounts = [
        StoredAccount(
            account_id="acct-1",
            email="user@example.com",
            access_token="tok",
            refresh_token="rtok",
            token_type="Bearer",
            scope="s",
            expiry_date=9999999999999,
            created_at="2026-02-02T00:00:00Z",
            updated_at="2026-02-02T00:00:00Z",
            last_used=None,
            needs_reauth=False,
        )
    ]
    selector._current_account = selector._accounts[0]

    reason = "To continue, verify your account at\n\nhttps://accounts.google.com/signin/continue?sarp=1"
    await selector.mark_current_account_blocked(reason)

    notification_service.send_notification.assert_awaited_once()
    _args, kwargs = notification_service.send_notification.call_args

    assert kwargs["title"] == "Gemini OAuth account needs verification"
    assert "user@example.com" in kwargs["message"]
    assert kwargs["url"].startswith("https://accounts.google.com/signin/continue")
    assert kwargs["url_label"] == "Verify account"
