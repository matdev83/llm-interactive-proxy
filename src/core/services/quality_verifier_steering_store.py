"""Best-effort storage for Quality Verifier steering notes.

Quality Verifier runs asynchronously after a backend response and may produce an
optional steering note. This note should be injected into a *future* backend
request (not surfaced to the client).

Implementation intentionally uses IApplicationState generic settings as a small,
in-memory store. This avoids needing to mutate session persistence layers from
deep response handlers and keeps the feature fail-open.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY = "quality_verifier_pending_steering_v1"
"""IApplicationState setting key storing pending steering notes.

Value is a dict mapping session_key -> dict with keys:
- message: str
- created_at: float (epoch seconds)
"""

MAX_STEERING_MESSAGE_CHARS = 4000


def _get_pending_map(app_state: Any) -> dict[str, dict[str, Any]]:
    try:
        raw: object = app_state.get_setting(
            PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {}
        )
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}

    # Defensive copy to avoid mutating shared dict references.
    pending: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, dict):
            pending[k] = dict(v)
        elif isinstance(v, str):
            pending[k] = {"message": v, "created_at": time.time()}
    return pending


def store_pending_quality_verifier_steering(
    *, app_state: Any, session_key: str, steering_message: str
) -> None:
    if not session_key:
        return
    msg = (steering_message or "").strip()
    if not msg:
        return
    if len(msg) > MAX_STEERING_MESSAGE_CHARS:
        msg = msg[:MAX_STEERING_MESSAGE_CHARS].rstrip() + "\n... (truncated)"

    pending = _get_pending_map(app_state)
    pending[session_key] = {"message": msg, "created_at": time.time()}

    try:
        app_state.set_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, pending)
    except Exception:
        return


def consume_pending_quality_verifier_steering(
    *, app_state: Any, session_key: str
) -> str | None:
    if not session_key:
        return None

    pending = _get_pending_map(app_state)
    record = pending.pop(session_key, None)
    if record is None:
        return None

    # Fail-open: even if we cannot clear, still return the message.
    with contextlib.suppress(Exception):
        app_state.set_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, pending)

    # record comes from _get_pending_map() and is expected to be a dict.
    msg = record.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()

    return None
