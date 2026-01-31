from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from src.core.config.env.util import (
    env_to_bool as _env_to_bool,
)
from src.core.config.env.util import (
    env_to_float as _env_to_float,
)
from src.core.config.env.util import (
    env_to_int as _env_to_int,
)
from src.core.config.env.util import (
    get_env_value as _get_env_value,
)
from src.core.config.env.util import (
    to_int as _to_int,
)
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.domain.configuration.replacement_rule import ReplacementRule

logger = logging.getLogger(__name__)


def _load_replacement_rules_from_env(
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
) -> list[ReplacementRule]:
    """Load replacement rules from REPLACEMENT_RULES environment variable.

    The environment variable should contain a JSON array of rule objects:
    [{"from_pattern": "*", "to_backend": "qwen-oauth", "to_model": "qwen3-coder-plus"}]

    Returns:
        List of ReplacementRule objects, or empty list if not set
    """
    replacement_rules_env = env.get("REPLACEMENT_RULES")
    if not replacement_rules_env:
        return []

    try:
        rules_data = json.loads(replacement_rules_env)
        if not isinstance(rules_data, list):
            logger.warning(
                "REPLACEMENT_RULES environment variable must be a JSON array. "
                f"Got: {type(rules_data).__name__}"
            )
            return []

        rules = []
        for i, rule_data in enumerate(rules_data):
            if not isinstance(rule_data, dict):
                logger.warning(
                    f"Replacement rule at index {i} must be an object. "
                    f"Skipping invalid rule."
                )
                continue

            try:
                rule = ReplacementRule(
                    from_pattern=rule_data.get("from_pattern", ""),
                    to_backend=rule_data.get("to_backend", ""),
                    to_model=rule_data.get("to_model", ""),
                )
                rules.append(rule)
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Invalid replacement rule at index {i}: {e}. Skipping rule."
                )
                continue

        # Record the whole list at once to avoid set_by_path creating a dict
        if resolution and rules:
            resolution.record(
                "replacement.replacement_rules",
                rules,
                ParameterSource.ENVIRONMENT,
                origin="REPLACEMENT_RULES",
            )

        return rules
    except json.JSONDecodeError as e:
        logger.warning(
            f"Failed to parse REPLACEMENT_RULES environment variable as JSON: {e}. "
            f"Ignoring replacement rules from environment."
        )
        return []


def apply_config_part3(
    config: dict[str, Any],
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
) -> None:
    config_backends: dict[str, Any] = config["backends"]
    assert isinstance(config_backends, dict)

    if env.get("OPENROUTER_API_KEY"):
        config_backends["openrouter"] = config_backends.get("openrouter", {})
        config_backends["openrouter"]["api_key"] = env["OPENROUTER_API_KEY"]
        config_backends["openrouter"]["api_url"] = _get_env_value(
            env,
            "OPENROUTER_API_BASE_URL",
            "https://openrouter.ai/api/v1",
            path="backends.openrouter.api_url",
            resolution=resolution,
        )
        timeout_value = _get_env_value(
            env,
            "OPENROUTER_TIMEOUT",
            None,
            path="backends.openrouter.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if timeout_value:
            config_backends["openrouter"]["timeout"] = timeout_value
        if resolution is not None:
            resolution.record(
                "backends.openrouter.api_key",
                config_backends["openrouter"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="OPENROUTER_API_KEY",
            )

    if env.get("GEMINI_API_KEY"):
        config_backends["gemini"] = config_backends.get("gemini", {})
        config_backends["gemini"]["api_key"] = env["GEMINI_API_KEY"]
        config_backends["gemini"]["api_url"] = _get_env_value(
            env,
            "GEMINI_API_BASE_URL",
            "https://generativelanguage.googleapis.com",
            path="backends.gemini.api_url",
            resolution=resolution,
        )
        gemini_timeout = _get_env_value(
            env,
            "GEMINI_TIMEOUT",
            None,
            path="backends.gemini.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if gemini_timeout:
            config_backends["gemini"]["timeout"] = gemini_timeout
        if resolution is not None:
            resolution.record(
                "backends.gemini.api_key",
                config_backends["gemini"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="GEMINI_API_KEY",
            )

    if env.get("ANTHROPIC_API_KEY"):
        config_backends["anthropic"] = config_backends.get("anthropic", {})
        config_backends["anthropic"]["api_key"] = env["ANTHROPIC_API_KEY"]
        config_backends["anthropic"]["api_url"] = _get_env_value(
            env,
            "ANTHROPIC_API_BASE_URL",
            "https://api.anthropic.com/v1",
            path="backends.anthropic.api_url",
            resolution=resolution,
        )
        anthropic_timeout = _get_env_value(
            env,
            "ANTHROPIC_TIMEOUT",
            None,
            path="backends.anthropic.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if anthropic_timeout:
            config_backends["anthropic"]["timeout"] = anthropic_timeout
        if resolution is not None:
            resolution.record(
                "backends.anthropic.api_key",
                config_backends["anthropic"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="ANTHROPIC_API_KEY",
            )

    if env.get("ZAI_API_KEY"):
        config_backends["zai"] = config_backends.get("zai", {})
        config_backends["zai"]["api_key"] = env["ZAI_API_KEY"]
        config_backends["zai"]["api_url"] = _get_env_value(
            env,
            "ZAI_API_BASE_URL",
            None,
            path="backends.zai.api_url",
            resolution=resolution,
        )
        zai_timeout = _get_env_value(
            env,
            "ZAI_TIMEOUT",
            None,
            path="backends.zai.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if zai_timeout:
            config_backends["zai"]["timeout"] = zai_timeout
        if resolution is not None:
            resolution.record(
                "backends.zai.api_key",
                config_backends["zai"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="ZAI_API_KEY",
            )

    if env.get("ZENMUX_API_KEY"):
        config_backends["zenmux"] = config_backends.get("zenmux", {})
        config_backends["zenmux"]["api_key"] = env["ZENMUX_API_KEY"]
        config_backends["zenmux"]["api_url"] = _get_env_value(
            env,
            "ZENMUX_API_BASE_URL",
            "https://zenmux.ai/api/v1",
            path="backends.zenmux.api_url",
            resolution=resolution,
        )
        zenmux_timeout = _get_env_value(
            env,
            "ZENMUX_TIMEOUT",
            None,
            path="backends.zenmux.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if zenmux_timeout:
            config_backends["zenmux"]["timeout"] = zenmux_timeout
        if resolution is not None:
            resolution.record(
                "backends.zenmux.api_key",
                config_backends["zenmux"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="ZENMUX_API_KEY",
            )

    if env.get("OPENAI_API_KEY"):
        config_backends["openai"] = config_backends.get("openai", {})
        config_backends["openai"]["api_key"] = env["OPENAI_API_KEY"]
        config_backends["openai"]["api_url"] = _get_env_value(
            env,
            "OPENAI_API_BASE_URL",
            "https://api.openai.com/v1",
            path="backends.openai.api_url",
            resolution=resolution,
        )
        openai_timeout = _get_env_value(
            env,
            "OPENAI_TIMEOUT",
            None,
            path="backends.openai.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if openai_timeout:
            config_backends["openai"]["timeout"] = openai_timeout
        if resolution is not None:
            resolution.record(
                "backends.openai.api_key",
                config_backends["openai"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="OPENAI_API_KEY",
            )

    if env.get("KIMI_API_KEY"):
        config_backends["kimi-code"] = config_backends.get("kimi-code", {})
        config_backends["kimi-code"]["api_key"] = env["KIMI_API_KEY"]
        config_backends["kimi-code"]["api_url"] = _get_env_value(
            env,
            "KIMI_API_BASE_URL",
            "https://api.kimi.com/coding/v1",
            path="backends.kimi-code.api_url",
            resolution=resolution,
        )
        kimi_timeout = _get_env_value(
            env,
            "KIMI_TIMEOUT",
            None,
            path="backends.kimi-code.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if kimi_timeout:
            config_backends["kimi-code"]["timeout"] = kimi_timeout
        if resolution is not None:
            resolution.record(
                "backends.kimi-code.api_key",
                config_backends["kimi-code"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="KIMI_API_KEY",
            )

    if env.get("MINIMAX_API_KEY"):
        config_backends["minimax"] = config_backends.get("minimax", {})
        config_backends["minimax"]["api_key"] = env["MINIMAX_API_KEY"]
        config_backends["minimax"]["api_url"] = _get_env_value(
            env,
            "MINIMAX_API_BASE_URL",
            "https://api.minimax.io/v1",
            path="backends.minimax.api_url",
            resolution=resolution,
        )
        minimax_timeout = _get_env_value(
            env,
            "MINIMAX_TIMEOUT",
            None,
            path="backends.minimax.timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        )
        if minimax_timeout:
            config_backends["minimax"]["timeout"] = minimax_timeout
        if resolution is not None:
            resolution.record(
                "backends.minimax.api_key",
                config_backends["minimax"]["api_key"],
                ParameterSource.ENVIRONMENT,
                origin="MINIMAX_API_KEY",
            )

    default_backend_type: str = str(config["backends"].get("default_backend", "openai"))
    if default_backend_type not in config_backends:
        config_backends[default_backend_type] = config_backends.get(
            default_backend_type, {}
        )
        if env.get("PYTEST_CURRENT_TEST") and (
            not config_backends[default_backend_type]
            or not config_backends[default_backend_type].get("api_key")
        ):
            config_backends[default_backend_type]["api_key"] = [
                f"test-key-{default_backend_type}"
            ]
            logger.info(
                "Added test API key for default backend %s", default_backend_type
            )

    # Load replacement rules and convert to dict format for config merging
    replacement_rules_objects = _load_replacement_rules_from_env(
        env, resolution=resolution
    )
    replacement_rules_dicts = [asdict(rule) for rule in replacement_rules_objects]

    config["replacement"] = {
        "enabled": _env_to_bool(
            "REPLACEMENT_ENABLED",
            False,
            env,
            path="replacement.enabled",
            resolution=resolution,
        ),
        "probability": _env_to_float(
            "REPLACEMENT_PROBABILITY",
            0.0,
            env,
            path="replacement.probability",
            resolution=resolution,
        ),
        # Handle new replacement_rules format (JSON array)
        "replacement_rules": replacement_rules_dicts,
        # Legacy backend_model for backward compatibility
        "backend_model": _get_env_value(
            env,
            "REPLACEMENT_BACKEND_MODEL",
            "",
            path="replacement.backend_model",
            resolution=resolution,
        ),
        "turn_count": _env_to_int(
            "REPLACEMENT_TURN_COUNT",
            1,
            env,
            path="replacement.turn_count",
            resolution=resolution,
        ),
        "allow_oauth_auto_replacement": _env_to_bool(
            "ALLOW_OAUTH_AUTO_REPLACEMENT",
            False,
            env,
            path="replacement.allow_oauth_auto_replacement",
            resolution=resolution,
        ),
    }

    # Notification settings
    if "LLM_PROXY_ENABLE_NOTIFICATIONS" in env:
        notifications_value = env["LLM_PROXY_ENABLE_NOTIFICATIONS"].strip().lower()
        config["notifications"] = {
            "enabled": notifications_value in {"1", "true", "yes", "on"}
        }
        if resolution is not None:
            resolution.record(
                "notifications.enabled",
                config["notifications"]["enabled"],
                ParameterSource.ENVIRONMENT,
                origin="LLM_PROXY_ENABLE_NOTIFICATIONS",
            )

    sso_enabled = _env_to_bool(
        "SSO_ENABLED",
        False,
        env,
        path="sso.enabled",
        resolution=resolution,
    )

    if sso_enabled:
        from src.core.auth.sso.config import (
            AuthorizationConfig,
            CaptchaConfig,
            SSOConfig,
        )

        captcha_enabled = _env_to_bool(
            "SSO_CAPTCHA_ENABLED",
            True,
            env,
            path="sso.captcha.enabled",
            resolution=resolution,
        )

        captcha_config = CaptchaConfig(
            enabled=captcha_enabled,
            provider=_get_env_value(
                env,
                "SSO_CAPTCHA_PROVIDER",
                "cloudflare_turnstile",
                path="sso.captcha.provider",
                resolution=resolution,
            ),
            site_key=_get_env_value(
                env,
                "SSO_CAPTCHA_SITE_KEY",
                None,
                path="sso.captcha.site_key",
                resolution=resolution,
            ),
            secret_key=_get_env_value(
                env,
                "SSO_CAPTCHA_SECRET_KEY",
                None,
                path="sso.captcha.secret_key",
                resolution=resolution,
            ),
            verify_url=_get_env_value(
                env,
                "SSO_CAPTCHA_VERIFY_URL",
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                path="sso.captcha.verify_url",
                resolution=resolution,
            ),
            widget_mode=_get_env_value(
                env,
                "SSO_CAPTCHA_WIDGET_MODE",
                "invisible",
                path="sso.captcha.widget_mode",
                resolution=resolution,
            ),
            timeout_seconds=_env_to_float(
                "SSO_CAPTCHA_TIMEOUT_SECONDS",
                5.0,
                env,
                path="sso.captcha.timeout_seconds",
                resolution=resolution,
            ),
        )

        config["sso"] = SSOConfig(
            enabled=True,
            session_lifetime_hours=_env_to_int(
                "SSO_SESSION_LIFETIME_HOURS",
                24,
                env,
                path="sso.session_lifetime_hours",
                resolution=resolution,
            ),
            database_path=_get_env_value(
                env,
                "SSO_DATABASE_PATH",
                "./var/sso_auth.db",
                path="sso.database_path",
                resolution=resolution,
            ),
            authorization=AuthorizationConfig(
                mode=_get_env_value(
                    env,
                    "SSO_AUTH_MODE",
                    "single_user",
                    path="sso.authorization.mode",
                    resolution=resolution,
                ),
                api_url=_get_env_value(
                    env,
                    "SSO_AUTH_API_URL",
                    None,
                    path="sso.authorization.api_url",
                    resolution=resolution,
                ),
                api_timeout=_env_to_int(
                    "SSO_AUTH_API_TIMEOUT",
                    30,
                    env,
                    path="sso.authorization.api_timeout",
                    resolution=resolution,
                ),
                confirmation_code_expiry_minutes=_env_to_int(
                    "SSO_CONFIRMATION_CODE_EXPIRY_MINUTES",
                    10,
                    env,
                    path="sso.authorization.confirmation_code_expiry_minutes",
                    resolution=resolution,
                ),
                max_confirmation_attempts=_env_to_int(
                    "SSO_MAX_CONFIRMATION_ATTEMPTS",
                    3,
                    env,
                    path="sso.authorization.max_confirmation_attempts",
                    resolution=resolution,
                ),
            ),
            captcha=captcha_config,
            providers={},
        )
    else:
        config["sso"] = None
