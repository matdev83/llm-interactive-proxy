from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping

from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def _normalize_backend_name(raw_name: str) -> str:
    """Normalize backend names to canonical hyphen form."""
    return raw_name.strip().lower().replace("_", "-")


def _backend_name_variants(raw_name: str) -> tuple[str, ...]:
    """Return canonical hyphen and underscore variants for backend lookups."""
    normalized = _normalize_backend_name(raw_name)
    variants: list[str] = []
    for candidate in (
        normalized,
        normalized.replace("-", "_"),
    ):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return tuple(variants)


def _env_base_variants(base_name: str) -> tuple[str, ...]:
    """Return env key base variants for robust hyphen/underscore matching."""
    base = base_name.strip()
    variants: list[str] = []
    for candidate in (
        base,
        base.replace("-", "_"),
        base.replace("_", "-"),
    ):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return tuple(variants)


def _env_keys_present(env: Mapping[str, str], base_name: str) -> bool:
    """Return True if base_name or any numbered variants are present."""
    for base in _env_base_variants(base_name):
        raw = env.get(base)
        if isinstance(raw, str) and raw.strip():
            return True

        for i in range(1, 21):
            raw_i = env.get(f"{base}_{i}")
            if isinstance(raw_i, str) and raw_i.strip():
                return True
    return False


def _env_hint(base_name: str) -> str:
    hints = [
        f"{base} (or {base}_1..{base}_20)" for base in _env_base_variants(base_name)
    ]
    return " / ".join(hints)


def _config_has_any_api_key(config: AppConfig, backend_type: str) -> bool:
    """Return True if backend_type itself or any numbered instance has an api_key."""
    lookup_names = _backend_name_variants(backend_type)
    prefixes = tuple(f"{name}." for name in lookup_names)
    # BackendSettings.lookup() does exact lookup without side-effects.
    for lookup_name in lookup_names:
        base_cfg = config.backends.lookup(lookup_name)
        if base_cfg is not None and base_cfg.api_key:
            return True

    for name, cfg in config.backends.get_named_backend_configs().items():
        if not isinstance(name, str) or not name.startswith(prefixes):
            continue
        if getattr(cfg, "api_key", None):
            return True
    return False


# Backends that are expected to be API-key-backed (directly or via env fallback).
#
# Important:
# - Some connectors (e.g. zai-coding-plan, kimi-code) read env vars directly even when
#   config is missing. Startup disablement must consider env presence, not just config.
# - Some connectors are not API-key-based (e.g. openai-codex uses an OAuth file) and
#   should not be disabled based on OPENAI_API_KEY.
_API_KEY_BACKENDS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai-responses": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "alibaba-token-plan-intl": "ALIBABA_TOKEN_PLAN_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "zenmux": "ZENMUX_API_KEY",
    "zai": "ZAI_API_KEY",
    "zai-coding-plan": "ZAI_CODING_PLAN_API_KEY",
    "kimi-code": "KIMI_API_KEY",
    "opencode-go": "OPENCODE_GO_API_KEY",
}


def compute_backends_to_disable_at_startup(
    *,
    config: AppConfig,
    registered_backends: Iterable[str],
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return mapping backend_type -> disable_reason for unusable API-key backends."""
    registered_by_normalized: dict[str, str] = {}
    for backend_name in registered_backends:
        if not isinstance(backend_name, str):
            continue
        normalized_name = _normalize_backend_name(backend_name)
        if normalized_name:
            registered_by_normalized.setdefault(normalized_name, backend_name)

    env_map: Mapping[str, str] = os.environ if env is None else env
    to_disable: dict[str, str] = {}

    for backend_type, env_base in _API_KEY_BACKENDS.items():
        registered_name = registered_by_normalized.get(
            _normalize_backend_name(backend_type)
        )
        if registered_name is None:
            continue

        # Consider both config and raw env presence.
        # - Config: needed for connectors that only consume kwargs (e.g. OpenAIConnector)
        # - Env: needed for connectors that fall back to os.environ (e.g. kimi-code)
        if _config_has_any_api_key(config, backend_type):
            continue

        # Some backends intentionally reuse another backend's credentials.
        # openai-responses uses the OpenAIConnector and should work when openai is configured.
        if backend_type == "openai-responses" and _config_has_any_api_key(
            config, "openai"
        ):
            continue

        if _env_keys_present(env_map, env_base):
            continue

        if backend_type == "openai-responses" and _env_keys_present(
            env_map, "OPENAI_API_KEY"
        ):
            continue
        if backend_type == "zai-coding-plan" and _env_keys_present(
            env_map, "ZAI_CODING_PLAN_API_KEY"
        ):
            continue

        to_disable[registered_name] = (
            "missing credentials "
            f"(config api_key unset; env {_env_hint(env_base)} not present in proxy process)"
        )

    return to_disable


def apply_backend_disablement_at_startup(
    *,
    config: AppConfig,
    registered_backends: Iterable[str],
    env: Mapping[str, str] | None = None,
    backend_lifecycle_manager: object,
) -> None:
    """Disable unusable API-key backends and log warnings.

    backend_lifecycle_manager is an object to keep this helper decoupled from the
    interface module at import time (avoids heavy imports during startup).
    It must provide a method: discard(backend_type: str, session_id: str | None, reason: str).
    """
    to_disable = compute_backends_to_disable_at_startup(
        config=config, registered_backends=registered_backends, env=env
    )
    if not to_disable:
        return

    discard = getattr(backend_lifecycle_manager, "discard", None)
    if not callable(discard):
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Backend disablement skipped: lifecycle manager lacks discard()"
            )
        return

    for backend_type, reason in sorted(to_disable.items()):
        try:
            discard(backend_type, None, reason)
        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to disable backend %s at startup: %s",
                    backend_type,
                    exc,
                    exc_info=True,
                )
            continue

        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Backend %s disabled at startup: %s", backend_type, reason)
