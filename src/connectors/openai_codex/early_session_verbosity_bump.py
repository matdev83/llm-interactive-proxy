"""Early-session verbosity/temperature bump for openai-codex Responses backends.

For the first N proxy session turns, force ``temperature=1`` and
``verbosity=high``. Applies only to ``openai-codex`` / ``openai-codex-v2``
(not app-server). Enabled by default; opt out via config.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_EARLY_SESSION_VERBOSITY_BUMP: dict[str, Any] = {
    "enabled": True,
    "max_turns": 5,
}

EARLY_SESSION_BUMP_FORCED_PARAMS: dict[str, Any] = {
    "temperature": 1.0,
    "verbosity": "high",
}

_OPENAI_CODEX_RESPONSES_FAMILIES = frozenset({"openai-codex", "openai-codex-v2"})


def normalize_backend_family(backend_type: str | None) -> str:
    """Normalize backend/instance names (e.g. ``openai-codex.1`` -> ``openai-codex``)."""
    if not isinstance(backend_type, str) or not backend_type.strip():
        return ""
    normalized = backend_type.strip().lower().replace("_", "-")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    return normalized


def is_openai_codex_responses_family(backend_type: str | None) -> bool:
    """Return True for openai-codex / openai-codex-v2 (including multi-instance)."""
    return normalize_backend_family(backend_type) in _OPENAI_CODEX_RESPONSES_FAMILIES


def normalize_early_session_verbosity_bump(
    raw: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge YAML/env mapping with defaults; coerce types safely."""
    base = dict(DEFAULT_EARLY_SESSION_VERBOSITY_BUMP)
    if not isinstance(raw, Mapping):
        return base

    if "enabled" in raw:
        base["enabled"] = bool(raw["enabled"])

    if "max_turns" in raw:
        try:
            max_turns = int(raw["max_turns"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            max_turns = int(DEFAULT_EARLY_SESSION_VERBOSITY_BUMP["max_turns"])
        base["max_turns"] = max(0, max_turns)

    return base


def session_history_len(session: Any | None) -> int:
    """Return proxy session interaction count; missing session => 0."""
    if session is None:
        return 0
    history = getattr(session, "history", None)
    if history is None:
        return 0
    try:
        return len(history)
    except TypeError:
        return 0


def should_apply_early_session_verbosity_bump(
    *,
    session: Any | None,
    backend_type: str | None,
    config: Mapping[str, Any] | None,
) -> bool:
    """Return whether early-session forced params should apply for this request."""
    if not is_openai_codex_responses_family(backend_type):
        return False

    normalized = normalize_early_session_verbosity_bump(config)
    if not normalized["enabled"]:
        return False

    max_turns = int(normalized["max_turns"])
    if max_turns <= 0:
        return False

    return session_history_len(session) < max_turns


def early_session_bump_forced_params(
    *,
    session: Any | None,
    backend_type: str | None,
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return forced param map when bump applies; otherwise empty dict."""
    if should_apply_early_session_verbosity_bump(
        session=session,
        backend_type=backend_type,
        config=config,
    ):
        return dict(EARLY_SESSION_BUMP_FORCED_PARAMS)
    return {}
