"""Tests for Codex quota desktop notification helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.openai_codex.codex_quota_notifications import (
    build_codex_quota_notification_message,
    maybe_notify_codex_quota_reached,
)


@pytest.mark.asyncio
async def test_all_accounts_exhausted_dedupes_across_different_account_ids() -> None:
    """When every account is exhausted, use one dedupe bucket for the whole pool."""
    mock_notify = AsyncMock(return_value="nid-1")
    svc = Mock()
    svc.is_enabled = True
    svc.send_notification = mock_notify
    dedupe: set[tuple[str, str, str]] = set()
    fixed_reset = 1_800_000_000
    fields: dict[str, object] = {
        "resets_in_seconds": 50_000.0,
        "resets_at_unix": fixed_reset,
    }

    await maybe_notify_codex_quota_reached(
        svc,
        dedupe,
        managed_account_id="acct_a",
        email="a@example.com",
        usage_limit_fields=fields,
        retry_after_seconds=None,
        all_accounts_exhausted=True,
    )
    await maybe_notify_codex_quota_reached(
        svc,
        dedupe,
        managed_account_id="acct_b",
        email="b@example.com",
        usage_limit_fields=fields,
        retry_after_seconds=None,
        all_accounts_exhausted=True,
    )

    assert mock_notify.await_count == 1


def test_build_codex_quota_notification_message_uses_storage_id_without_email() -> None:
    msg = build_codex_quota_notification_message(
        email=None,
        managed_account_id="my-work-account",
        chatgpt_account_id=None,
        quota_type="weekly limit",
        until_display="2099-01-01T00:00:00+00:00",
        all_accounts_exhausted=False,
    )
    assert "Account: my-work-account" in msg


def test_build_codex_quota_notification_message_prefers_email_over_ids() -> None:
    msg = build_codex_quota_notification_message(
        email="u@example.com",
        managed_account_id="slug",
        chatgpt_account_id="uuid-1",
        quota_type="weekly limit",
        until_display="2099-01-01T00:00:00+00:00",
        all_accounts_exhausted=False,
    )
    assert "Account: u@example.com" in msg
    assert "uuid-1" not in msg.split("type:")[0]


def test_build_codex_quota_notification_message_uses_chatgpt_when_no_email() -> None:
    msg = build_codex_quota_notification_message(
        email=None,
        managed_account_id="slug",
        chatgpt_account_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        quota_type="sliding 5h window",
        until_display="2099-01-01T00:00:00+00:00",
        all_accounts_exhausted=False,
    )
    assert "cccccccc-cccc-cccc-cccc-cccccccccccc" in msg


@pytest.mark.asyncio
async def test_maybe_notify_derives_quota_type_from_resets_at_unix() -> None:
    """When upstream omits resets_in_seconds, derive interval from resets_at for labels."""
    mock_notify = AsyncMock(return_value="nid-2")
    svc = Mock()
    svc.is_enabled = True
    svc.send_notification = mock_notify
    dedupe: set[tuple[str, str, str]] = set()
    fixed_now = 1_700_000_000.0
    # ~4.6 days ahead -> extended window -> user-facing "weekly limit"
    fields: dict[str, object] = {
        "resets_at_unix": int(fixed_now + 400_000),
    }

    import src.connectors.openai_codex.codex_quota_notifications as cq

    with patch.object(cq.time, "time", return_value=fixed_now):
        await maybe_notify_codex_quota_reached(
            svc,
            dedupe,
            managed_account_id="acct_z",
            email=None,
            chatgpt_account_id="gggggggg-gggg-gggg-gggg-gggggggggggg",
            usage_limit_fields=fields,
            retry_after_seconds=None,
            all_accounts_exhausted=False,
        )

    message = mock_notify.call_args.kwargs["message"]
    assert "weekly limit" in message
    assert "gggggggg-gggg-gggg-gggg-gggggggggggg" in message
