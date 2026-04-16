"""
Resilience scoping helpers.

Personal OAuth-style backends should not share resilience state across users.
This helper derives a stable scope key from request context when available.
"""

from __future__ import annotations

from src.core.domain.request_context import RequestContext

_PERSONAL_BACKEND_TYPES = frozenset(
    [
        "antigravity-oauth",
        "gemini-cli-cloud-project",
        "gemini-oauth-free",
        "gemini-oauth-plan",
        "openai-codex",
        "openai-codex-v2",
        "opencode-zen",
        "qwen-oauth",
    ]
)


def _resolve_resilience_config(
    context: RequestContext | None,
) -> object | None:
    if context is None:
        return None
    app_state = getattr(context, "app_state", None)
    if app_state is None:
        return None
    config = getattr(app_state, "app_config", None)
    if config is None:
        getter = getattr(app_state, "get_setting", None)
        if callable(getter):
            config = getter("app_config")
    return getattr(config, "resilience", None) if config is not None else None


def _normalize_backend_list(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def is_personal_backend_type(
    backend_type: str, context: RequestContext | None = None
) -> bool:
    """Return True for backends that should be scoped per user/session."""
    normalized = backend_type.lower()
    resilience = _resolve_resilience_config(context)
    if resilience is not None:
        shared = _normalize_backend_list(
            getattr(resilience, "shared_backend_types", None)
        )
        personal = _normalize_backend_list(
            getattr(resilience, "personal_backend_types", None)
        )
        if normalized in shared:
            return False
        if normalized in personal:
            return True

    if normalized in _PERSONAL_BACKEND_TYPES:
        return True
    return "oauth" in normalized or "codex" in normalized


def build_resilience_instance_id(
    backend_type: str, context: RequestContext | None
) -> str:
    """Build a resilience instance id, scoping personal backends when possible."""
    if not is_personal_backend_type(backend_type, context):
        return backend_type

    if context is not None:
        for candidate in (context.session_id, context.client_host):
            if candidate is not None:
                candidate_str = str(candidate).strip()
                if candidate_str:
                    return f"{backend_type}:{candidate_str}"

    return backend_type


def build_resilience_error_context(
    backend_type: str, context: RequestContext | None
) -> dict[str, object]:
    """Build extra context to attach to failures for handler decisions."""
    return {
        "backend_type": backend_type,
        "is_personal_backend": is_personal_backend_type(backend_type, context),
        "session_id": getattr(context, "session_id", None),
        "client_host": getattr(context, "client_host", None),
    }
