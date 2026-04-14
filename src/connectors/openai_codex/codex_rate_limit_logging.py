"""Structured logging for OpenAI Codex upstream usage / rate limits."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Codex "primary" rolling windows are on the order of a few hours; weekly-style
# resets are much longer. This boundary is heuristic (provider-specific).
_SHORT_ROLLING_CEILING_SECONDS = 6 * 3600


def parse_codex_usage_limit_upstream(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """If payload is Codex ``usage_limit_reached``, return normalized fields."""
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    if error.get("type") != "usage_limit_reached":
        return None

    resets_in_raw = error.get("resets_in_seconds")
    resets_in: float | None = None
    if isinstance(resets_in_raw, int | float) and float(resets_in_raw) > 0:
        resets_in = float(resets_in_raw)

    resets_at_raw = error.get("resets_at")
    resets_at_unix: int | None = None
    if isinstance(resets_at_raw, int | float) and float(resets_at_raw) > 1_000_000_000:
        resets_at_unix = int(resets_at_raw)

    plan_type = error.get("plan_type")
    plan_type_str = plan_type if isinstance(plan_type, str) else None

    message = error.get("message")
    message_str = message if isinstance(message, str) else None

    return {
        "error_type": "usage_limit_reached",
        "plan_type": plan_type_str,
        "resets_in_seconds": resets_in,
        "resets_at_unix": resets_at_unix,
        "message": message_str,
    }


def classify_usage_limit_window(resets_in_seconds: float | None) -> str:
    """Roughly classify which limit bucket the reset interval suggests."""
    if resets_in_seconds is None or resets_in_seconds <= 0:
        return "unknown"
    if resets_in_seconds <= _SHORT_ROLLING_CEILING_SECONDS:
        return "short_rolling (~few_hour_window)"
    if resets_in_seconds <= 48 * 3600:
        return "multi_hour_to_daily"
    return "extended (~weekly_or_plan_quota)"


def _available_again_iso(
    *,
    resets_at_unix: int | None,
    retry_after_seconds: float | None,
) -> str | None:
    if isinstance(resets_at_unix, int) and resets_at_unix > 1_000_000_000:
        return datetime.fromtimestamp(
            float(resets_at_unix), tz=timezone.utc
        ).isoformat()
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return datetime.fromtimestamp(
            time.time() + float(retry_after_seconds), tz=timezone.utc
        ).isoformat()
    return None


def emit_openai_codex_managed_oauth_rate_limit(
    *,
    managed_account_id: str | None,
    email: str | None,
    chatgpt_account_id: str | None,
    retry_after_seconds: float | None,
    session_id: str | None,
    upstream_json: Mapping[str, Any] | None,
    log: logging.Logger | None = None,
) -> None:
    """Emit a dedicated WARNING line when a managed account is marked rate-limited."""
    sink = log or logger
    if not sink.isEnabledFor(logging.WARNING):
        return

    parsed = (
        parse_codex_usage_limit_upstream(upstream_json)
        if upstream_json is not None
        else None
    )
    resets_in = parsed.get("resets_in_seconds") if parsed else None
    if not isinstance(resets_in, int | float) or resets_in <= 0:
        resets_in = retry_after_seconds

    window = classify_usage_limit_window(
        float(resets_in) if isinstance(resets_in, int | float) else None
    )
    resets_at_unix: int | None = None
    if parsed:
        rat = parsed.get("resets_at_unix")
        if isinstance(rat, int):
            resets_at_unix = rat
    available = _available_again_iso(
        resets_at_unix=resets_at_unix,
        retry_after_seconds=retry_after_seconds,
    )

    plan = parsed.get("plan_type") if parsed else None
    err_type = parsed.get("error_type") if parsed else None
    upstream_msg = parsed.get("message") if parsed else None

    sink.warning(
        "OpenAI Codex managed OAuth: upstream rate limit for account "
        "managed_account_id=%r email=%r chatgpt_account_id=%r "
        "session_id=%r codex_error_type=%r plan_type=%r limit_window=%r "
        "retry_after_seconds=%r resets_at_utc=%r upstream_message=%r",
        managed_account_id,
        email,
        chatgpt_account_id,
        session_id,
        err_type,
        plan,
        window,
        retry_after_seconds,
        available,
        upstream_msg,
        extra={
            "backend": "openai-codex",
            "openai_codex_rate_limit": True,
            "managed_account_id": managed_account_id,
            "email": email,
            "chatgpt_account_id": chatgpt_account_id,
            "session_id": session_id,
            "codex_error_type": err_type,
            "plan_type": plan,
            "limit_window": window,
            "retry_after_seconds": retry_after_seconds,
            "resets_in_seconds": parsed.get("resets_in_seconds") if parsed else None,
            "resets_at_utc": available,
        },
    )
