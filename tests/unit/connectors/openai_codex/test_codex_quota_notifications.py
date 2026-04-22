"""Tests for Codex quota desktop notification helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.openai_codex.codex_quota_notifications import (
    build_codex_quota_notification_message,
    collect_codex_remaining_pairs,
    maybe_notify_codex_quota_reached,
    maybe_notify_codex_quota_remaining_low,
)


@pytest.mark.asyncio
async def test_pool_exhaustion_confirmed_dedupes_across_different_account_ids() -> None:
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
        pool_exhaustion_confirmed=True,
    )
    await maybe_notify_codex_quota_reached(
        svc,
        dedupe,
        managed_account_id="acct_b",
        email="b@example.com",
        usage_limit_fields=fields,
        retry_after_seconds=None,
        pool_exhaustion_confirmed=True,
    )

    assert mock_notify.await_count == 1


def test_build_codex_quota_notification_message_uses_storage_id_without_email() -> None:
    msg = build_codex_quota_notification_message(
        email=None,
        managed_account_id="my-work-account",
        chatgpt_account_id=None,
        quota_type="weekly limit",
        until_display="2099-01-01T00:00:00+00:00",
        pool_exhaustion_confirmed=False,
    )
    assert "Account: my-work-account" in msg


def test_build_codex_quota_notification_message_prefers_email_over_ids() -> None:
    msg = build_codex_quota_notification_message(
        email="u@example.com",
        managed_account_id="slug",
        chatgpt_account_id="uuid-1",
        quota_type="weekly limit",
        until_display="2099-01-01T00:00:00+00:00",
        pool_exhaustion_confirmed=False,
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
        pool_exhaustion_confirmed=False,
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
            pool_exhaustion_confirmed=False,
        )

    message = mock_notify.call_args.kwargs["message"]
    assert "weekly limit" in message
    assert "gggggggg-gggg-gggg-gggg-gggggggggggg" in message


def test_collect_codex_remaining_pairs_primary_and_secondary() -> None:
    headers = {
        "X-Codex-Primary-Used-Percent": "72",
        "x-codex-secondary-used-percent": "25.0",
    }
    pairs = collect_codex_remaining_pairs(headers)
    assert pairs == [("primary", 28.0), ("secondary", 75.0)]


@pytest.mark.asyncio
async def test_maybe_notify_codex_quota_remaining_low_latches_until_recovery() -> None:
    mock_notify = AsyncMock(return_value="nid-r1")
    svc = Mock()
    svc.is_enabled = True
    svc.send_notification = mock_notify
    latch: set[tuple[str, str, float]] = set()
    headers_primary = {"x-codex-primary-used-percent": "80"}

    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-1",
        email="u@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0, 10.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers_primary),
    )
    assert mock_notify.await_count == 1

    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-1",
        email="u@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0, 10.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers_primary),
    )
    assert mock_notify.await_count == 1

    headers_recover = {"x-codex-primary-used-percent": "70"}
    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-1",
        email="u@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0, 10.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers_recover),
    )
    assert mock_notify.await_count == 1

    headers_low_again = {"x-codex-primary-used-percent": "80"}
    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-1",
        email="u@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0, 10.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers_low_again),
    )
    assert mock_notify.await_count == 2


@pytest.mark.asyncio
async def test_maybe_notify_codex_quota_remaining_low_primary_secondary_independent() -> (
    None
):
    mock_notify = AsyncMock(return_value="nid-r2")
    svc = Mock()
    svc.is_enabled = True
    svc.send_notification = mock_notify
    latch: set[tuple[str, str, float]] = set()
    headers = {
        "x-codex-primary-used-percent": "90",
        "x-codex-secondary-used-percent": "92",
    }
    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-2",
        email=None,
        chatgpt_account_id="cg-uuid",
        threshold_percents=[25.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers),
    )
    assert mock_notify.await_count == 2


@pytest.mark.asyncio
async def test_maybe_notify_codex_quota_remaining_low_disabled_service() -> None:
    mock_notify = AsyncMock(return_value="nid-r3")
    svc = Mock()
    svc.is_enabled = False
    svc.send_notification = mock_notify
    latch: set[tuple[str, str, float]] = set()
    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-3",
        email="x@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0],
        remaining_by_limit=[("primary", 5.0)],
    )
    assert mock_notify.await_count == 0


@pytest.mark.asyncio
async def test_maybe_notify_codex_quota_remaining_low_fires_two_thresholds() -> None:
    mock_notify = AsyncMock(return_value="nid-r4")
    svc = Mock()
    svc.is_enabled = True
    svc.send_notification = mock_notify
    latch: set[tuple[str, str, float]] = set()
    # 8% remaining -> below 25 and below 10
    headers = {"x-codex-primary-used-percent": "92"}
    await maybe_notify_codex_quota_remaining_low(
        svc,
        latch,
        managed_account_id="acct-4",
        email="e@example.com",
        chatgpt_account_id=None,
        threshold_percents=[25.0, 10.0],
        remaining_by_limit=collect_codex_remaining_pairs(headers),
    )
    assert mock_notify.await_count == 2
