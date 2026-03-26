from __future__ import annotations

from collections.abc import Mapping
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
    get_api_keys_from_env as _get_api_keys_from_env,
)
from src.core.config.env.util import (
    get_env_value as _get_env_value,
)
from src.core.config.env.util import (
    to_float as _to_float,
)
from src.core.config.env.util import (
    to_int as _to_int,
)
from src.core.config.parameter_resolution import ParameterResolution


def build_config_part1a(
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config: dict[str, Any] = {
        "gcp_project_id": _get_env_value(
            env,
            "GOOGLE_CLOUD_PROJECT",
            _get_env_value(
                env,
                "GCP_PROJECT_ID",
                None,
                path="gcp_project_id",
                resolution=resolution,
            ),
            path="gcp_project_id",
            resolution=resolution,
        ),
        "gemini_credentials_path": _get_env_value(
            env,
            "GEMINI_CREDENTIALS_PATH",
            None,
            path="gemini_credentials_path",
            resolution=resolution,
        ),
        "disable_health_checks": _env_to_bool(
            "DISABLE_HEALTH_CHECKS",
            False,
            env,
            path="disable_health_checks",
            resolution=resolution,
        ),
        "enable_activity_tracking": _env_to_bool(
            "ENABLE_ACTIVITY_TRACKING",
            False,
            env,
            path="enable_activity_tracking",
            resolution=resolution,
        ),
        "auto_append_first_prompt_filename": _get_env_value(
            env,
            "AUTO_APPEND_FIRST_PROMPT_FILENAME",
            None,
            path="auto_append_first_prompt_filename",
            resolution=resolution,
        ),
        "request_dedup_window": _env_to_float(
            "LLM_REQUEST_DEDUP_WINDOW",
            3.0,
            env,
            path="request_dedup_window",
            resolution=resolution,
        ),
        "request_dedup_max_cache": _env_to_int(
            "LLM_REQUEST_DEDUP_MAX_CACHE",
            10000,
            env,
            path="request_dedup_max_cache",
            resolution=resolution,
        ),
        "host": _get_env_value(
            env,
            "APP_HOST",
            "127.0.0.1",
            path="host",
            resolution=resolution,
        ),
        "port": _get_env_value(
            env,
            "APP_PORT",
            8000,
            path="port",
            resolution=resolution,
            transform=lambda value: _to_int(value, 8000),
        ),
        "public_url": _get_env_value(
            env,
            "PUBLIC_URL",
            None,
            path="public_url",
            resolution=resolution,
        ),
        "anthropic_port": _get_env_value(
            env,
            "ANTHROPIC_PORT",
            None,
            path="anthropic_port",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0) if value else None,
        ),
        "proxy_timeout": _get_env_value(
            env,
            "PROXY_TIMEOUT",
            120,
            path="proxy_timeout",
            resolution=resolution,
            transform=lambda value: _to_int(value, 120),
        ),
        "command_prefix": _get_env_value(
            env,
            "COMMAND_PREFIX",
            "!/",
            path="command_prefix",
            resolution=resolution,
        ),
        "auth": {
            "disable_auth": _env_to_bool(
                "DISABLE_AUTH",
                False,
                env,
                path="auth.disable_auth",
                resolution=resolution,
            ),
            "api_keys": _get_api_keys_from_env(env, resolution),
            "auth_token": _get_env_value(
                env,
                "AUTH_TOKEN",
                None,
                path="auth.auth_token",
                resolution=resolution,
            ),
            "brute_force_protection": {
                "enabled": _env_to_bool(
                    "BRUTE_FORCE_PROTECTION_ENABLED",
                    True,
                    env,
                    path="auth.brute_force_protection.enabled",
                    resolution=resolution,
                ),
                "max_failed_attempts": _env_to_int(
                    "BRUTE_FORCE_MAX_FAILED_ATTEMPTS",
                    5,
                    env,
                    path="auth.brute_force_protection.max_failed_attempts",
                    resolution=resolution,
                ),
                "ttl_seconds": _env_to_int(
                    "BRUTE_FORCE_TTL_SECONDS",
                    900,
                    env,
                    path="auth.brute_force_protection.ttl_seconds",
                    resolution=resolution,
                ),
                "initial_block_seconds": _env_to_int(
                    "BRUTE_FORCE_INITIAL_BLOCK_SECONDS",
                    30,
                    env,
                    path="auth.brute_force_protection.initial_block_seconds",
                    resolution=resolution,
                ),
                "block_multiplier": _env_to_float(
                    "BRUTE_FORCE_BLOCK_MULTIPLIER",
                    2.0,
                    env,
                    path="auth.brute_force_protection.block_multiplier",
                    resolution=resolution,
                ),
                "max_block_seconds": _env_to_int(
                    "BRUTE_FORCE_MAX_BLOCK_SECONDS",
                    3600,
                    env,
                    path="auth.brute_force_protection.max_block_seconds",
                    resolution=resolution,
                ),
            },
        },
    }

    auth_config: dict[str, Any] = config["auth"]
    if isinstance(auth_config, dict) and auth_config.get("disable_auth"):
        auth_config["api_keys"] = []

    planning_overrides: dict[str, Any] = {}
    planning_temperature = _get_env_value(
        env,
        "PLANNING_PHASE_TEMPERATURE",
        None,
        path="session.planning_phase.overrides.temperature",
        resolution=resolution,
        transform=lambda value: _to_float(value, None),
    )
    if planning_temperature is not None:
        planning_overrides["temperature"] = planning_temperature

    planning_top_p = _get_env_value(
        env,
        "PLANNING_PHASE_TOP_P",
        None,
        path="session.planning_phase.overrides.top_p",
        resolution=resolution,
        transform=lambda value: _to_float(value, None),
    )
    if planning_top_p is not None:
        planning_overrides["top_p"] = planning_top_p

    planning_reasoning = _get_env_value(
        env,
        "PLANNING_PHASE_REASONING_EFFORT",
        None,
        path="session.planning_phase.overrides.reasoning_effort",
        resolution=resolution,
    )
    if planning_reasoning is not None:
        planning_overrides["reasoning_effort"] = planning_reasoning

    planning_budget = _get_env_value(
        env,
        "PLANNING_PHASE_THINKING_BUDGET",
        None,
        path="session.planning_phase.overrides.thinking_budget",
        resolution=resolution,
        transform=lambda value: _to_int(value, 0),
    )
    if planning_budget is not None:
        planning_overrides["thinking_budget"] = planning_budget

    return config, planning_overrides
