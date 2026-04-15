"""Tests for Codex quota desktop notification helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.openai_codex.codex_quota_notifications import (
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
