"""Desktop notifications for OpenAI Codex managed-OAuth quota / rate limits."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.connectors.openai_codex.codex_rate_limit_logging import (
    classify_usage_limit_window,
    compute_codex_quota_until_iso_utc,
)

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import (
        INotificationService,
    )

logger = logging.getLogger(__name__)

_CODEX_QUOTA_NOTIFICATION_TITLE = "OpenAI Codex: Quota reached"

# Dedupe key component when every managed account is simultaneously unavailable:
# one desktop alert per quota window, not one per account that hits 429 last.
_CODEX_QUOTA_ALL_ACCOUNTS_DEDUPE_ID = "__all_managed_accounts__"

_EXTENDED_WINDOW = "extended (~weekly_or_plan_quota)"


def _format_account_label(
    email: str | None,
    *,
    managed_account_id: str | None,
    chatgpt_account_id: str | None,
) -> str:
    """Best-effort human-readable account reference for desktop notifications."""
    if isinstance(email, str) and email.strip():
        return email.strip()
    if isinstance(chatgpt_account_id, str) and chatgpt_account_id.strip():
        return chatgpt_account_id.strip()
    if isinstance(managed_account_id, str) and managed_account_id.strip():
        return managed_account_id.strip()
    return "(unknown)"


def user_facing_quota_type(resets_in_seconds: float | None) -> str:
    """Map heuristic window to the two primary Codex limit labels (plus unknown)."""
    window = classify_usage_limit_window(resets_in_seconds)
    if window == "unknown":
        return "unknown"
    if window == _EXTENDED_WINDOW:
        return "weekly limit"
    return "sliding 5h window"


def build_codex_quota_notification_message(
    *,
    email: str | None,
    managed_account_id: str | None = None,
    chatgpt_account_id: str | None = None,
    quota_type: str,
    until_display: str,
    pool_exhaustion_confirmed: bool,
) -> str:
    """Body text for a Codex quota desktop notification."""
    account = _format_account_label(
        email,
        managed_account_id=managed_account_id,
        chatgpt_account_id=chatgpt_account_id,
    )
    msg = (
        f"Codex quota reached. Account: {account}, type: {quota_type}, "
        f"until: {until_display}"
    )
    if pool_exhaustion_confirmed:
        msg += "\n\nQuotas exhausted on all available accounts"
    return msg


def _effective_resets_in_seconds(
    usage_limit_fields: Mapping[str, Any] | None,
    retry_after_seconds: float | None,
) -> float | None:
    if usage_limit_fields:
        raw = usage_limit_fields.get("resets_in_seconds")
        if isinstance(raw, int | float) and float(raw) > 0:
            return float(raw)
        rat_unix = usage_limit_fields.get("resets_at_unix")
        if isinstance(rat_unix, int) and rat_unix > 1_000_000_000:
            derived = float(rat_unix) - time.time()
            if derived > 0:
                return derived
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return float(retry_after_seconds)
    return None


def _resets_at_unix_from_fields(
    usage_limit_fields: Mapping[str, Any] | None,
) -> int | None:
    if not usage_limit_fields:
        return None
    rat = usage_limit_fields.get("resets_at_unix")
    return rat if isinstance(rat, int) else None


async def maybe_notify_codex_quota_reached(
    notification_service: INotificationService | None,
    dedupe_keys: set[tuple[str, str, str]],
    *,
    managed_account_id: str,
    email: str | None,
    chatgpt_account_id: str | None = None,
    usage_limit_fields: dict[str, Any] | None,
    retry_after_seconds: float | None,
    pool_exhaustion_confirmed: bool,
) -> None:
    """Send at most one desktop notification per dedupe key while service is enabled.

    Args:
        pool_exhaustion_confirmed: If True, uses global dedupe key and adds "all accounts exhausted"
            message. If False, uses per-account dedupe for notifications.
    """
    if notification_service is None or not notification_service.is_enabled:
        return

    resets_in = _effective_resets_in_seconds(usage_limit_fields, retry_after_seconds)
    quota_type = user_facing_quota_type(resets_in)
    until_iso = compute_codex_quota_until_iso_utc(
        resets_at_unix=_resets_at_unix_from_fields(usage_limit_fields),
        retry_after_seconds=retry_after_seconds,
    )
    until_display = until_iso if until_iso else "unknown"
    dedupe_until = until_iso if until_iso else "none"

    dedupe_account_id = (
        _CODEX_QUOTA_ALL_ACCOUNTS_DEDUPE_ID
        if pool_exhaustion_confirmed
        else managed_account_id
    )
    key = (dedupe_account_id, quota_type, dedupe_until)
    if key in dedupe_keys:
        return

    message = build_codex_quota_notification_message(
        email=email,
        managed_account_id=managed_account_id,
        chatgpt_account_id=chatgpt_account_id,
        quota_type=quota_type,
        until_display=until_display,
        pool_exhaustion_confirmed=pool_exhaustion_confirmed,
    )
    try:
        await notification_service.send_notification(
            title=_CODEX_QUOTA_NOTIFICATION_TITLE,
            message=message,
        )
    except Exception as exc:
        logger.warning("Codex quota notification failed: %s", exc, exc_info=True)
        return

    dedupe_keys.add(key)
