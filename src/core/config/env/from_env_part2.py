from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, cast

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
    parse_csv_list as _parse_csv_list,
)
from src.core.config.models.backends import (
    DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE,
)
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.header_config import HeaderConfig, HeaderOverrideMode

logger = logging.getLogger(__name__)


def apply_config_part2(
    config: dict[str, Any],
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
) -> None:
    failure_handling_enabled = not _env_to_bool(
        "DISABLE_FAILURE_HANDLING",
        False,
        env,
        path="failure_handling.enabled",
        resolution=resolution,
    )
    config["failure_handling"] = {
        "enabled": failure_handling_enabled,
        "max_silent_wait": _env_to_float(
            "FAILURE_HANDLING_MAX_SILENT_WAIT",
            30.0,
            env,
            path="failure_handling.max_silent_wait",
            resolution=resolution,
        ),
        "total_timeout_budget": _env_to_float(
            "FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET",
            90.0,
            env,
            path="failure_handling.total_timeout_budget",
            resolution=resolution,
        ),
        "keepalive_interval": _env_to_float(
            "FAILURE_HANDLING_KEEPALIVE_INTERVAL",
            8.0,
            env,
            path="failure_handling.keepalive_interval",
            resolution=resolution,
        ),
        "max_failover_hops": _env_to_int(
            "FAILURE_HANDLING_MAX_FAILOVER_HOPS",
            5,
            env,
            path="failure_handling.max_failover_hops",
            resolution=resolution,
        ),
        "min_retry_wait": _env_to_float(
            "FAILURE_HANDLING_MIN_RETRY_WAIT",
            1.0,
            env,
            path="failure_handling.min_retry_wait",
            resolution=resolution,
        ),
    }

    config["resilience"] = {
        "personal_backend_types": _get_env_value(
            env,
            "RESILIENCE_PERSONAL_BACKEND_TYPES",
            [],
            path="resilience.personal_backend_types",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "shared_backend_types": _get_env_value(
            env,
            "RESILIENCE_SHARED_BACKEND_TYPES",
            [],
            path="resilience.shared_backend_types",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
    }

    config["sandboxing"] = {
        "enabled": _env_to_bool(
            "ENABLE_SANDBOXING",
            False,
            env,
            path="sandboxing.enabled",
            resolution=resolution,
        ),
        "strict_mode": _env_to_bool(
            "SANDBOXING_STRICT_MODE",
            False,
            env,
            path="sandboxing.strict_mode",
            resolution=resolution,
        ),
        "allow_parent_access": _env_to_bool(
            "SANDBOXING_ALLOW_PARENT_ACCESS",
            False,
            env,
            path="sandboxing.allow_parent_access",
            resolution=resolution,
        ),
    }

    config["end_of_session"] = {
        "enabled": _env_to_bool(
            "END_OF_SESSION_ENABLED",
            False,
            env,
            path="end_of_session.enabled",
            resolution=resolution,
        ),
        "emit_events": _env_to_bool(
            "END_OF_SESSION_EMIT_EVENTS",
            True,
            env,
            path="end_of_session.emit_events",
            resolution=resolution,
        ),
        "detect_stream_signals": _env_to_bool(
            "END_OF_SESSION_DETECT_STREAM_SIGNALS",
            True,
            env,
            path="end_of_session.detect_stream_signals",
            resolution=resolution,
        ),
        "detect_tool_completion": _env_to_bool(
            "END_OF_SESSION_DETECT_TOOL_COMPLETION",
            True,
            env,
            path="end_of_session.detect_tool_completion",
            resolution=resolution,
        ),
        "emission_ttl_seconds": _env_to_int(
            "END_OF_SESSION_EMISSION_TTL_SECONDS",
            3600,
            env,
            path="end_of_session.emission_ttl_seconds",
            resolution=resolution,
        ),
        "dispatch_timeout_seconds": _env_to_float(
            "END_OF_SESSION_DISPATCH_TIMEOUT_SECONDS",
            5.0,
            env,
            path="end_of_session.dispatch_timeout_seconds",
            resolution=resolution,
        ),
    }

    model_aliases_env = env.get("MODEL_ALIASES")
    if model_aliases_env:
        try:
            alias_data = json.loads(model_aliases_env)
            if isinstance(alias_data, list):
                config["model_aliases"] = [
                    {"pattern": entry["pattern"], "replacement": entry["replacement"]}
                    for entry in cast("list[dict[str, Any]]", alias_data)
                    if "pattern" in entry and "replacement" in entry
                ]
                if resolution is not None:
                    resolution.record(
                        "model_aliases",
                        config["model_aliases"],
                        ParameterSource.ENVIRONMENT,
                        origin="MODEL_ALIASES",
                    )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Invalid MODEL_ALIASES environment variable format: %s",
                exc,
                exc_info=True,
            )
            config["model_aliases"] = []
    else:
        config["model_aliases"] = []

    config["backends"] = {
        "default_backend": _get_env_value(
            env,
            "LLM_BACKEND",
            "openai",
            path="backends.default_backend",
            resolution=resolution,
        ),
        "disable_gemini_oauth_fallback": _env_to_bool(
            "DISABLE_GEMINI_OAUTH_FALLBACK",
            False,
            env,
            path="backends.disable_gemini_oauth_fallback",
            resolution=resolution,
        ),
        "disable_gemini_oauth_reasoning_prompt_injection": _env_to_bool(
            "DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION",
            False,
            env,
            path="backends.disable_gemini_oauth_reasoning_prompt_injection",
            resolution=resolution,
        ),
        "disable_hybrid_backend": _env_to_bool(
            "DISABLE_HYBRID_BACKEND",
            False,
            env,
            path="backends.disable_hybrid_backend",
            resolution=resolution,
        ),
        "hybrid_backend_repeat_messages": _env_to_bool(
            "HYBRID_BACKEND_REPEAT_MESSAGES",
            False,
            env,
            path="backends.hybrid_backend_repeat_messages",
            resolution=resolution,
        ),
        "reasoning_injection_probability": _env_to_float(
            "REASONING_INJECTION_PROBABILITY",
            1.0,
            env,
            path="backends.reasoning_injection_probability",
            resolution=resolution,
        ),
        "hybrid_reasoning_model_timeout": _env_to_int(
            "HYBRID_REASONING_MODEL_TIMEOUT",
            60,
            env,
            path="backends.hybrid_reasoning_model_timeout",
            resolution=resolution,
        ),
        "hybrid_reasoning_force_initial_turns": _env_to_int(
            "HYBRID_REASONING_FORCE_INITIAL_TURNS",
            1,
            env,
            path="backends.hybrid_reasoning_force_initial_turns",
            resolution=resolution,
        ),
        "hybrid_execution_model_timeout": _env_to_int(
            "HYBRID_EXECUTION_MODEL_TIMEOUT",
            120,
            env,
            path="backends.hybrid_execution_model_timeout",
            resolution=resolution,
        ),
        "interleaved_thinking_instructions_file": _get_env_value(
            env,
            "INTERLEAVED_THINKING_INSTRUCTIONS_FILE",
            DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE,
            path="backends.interleaved_thinking_instructions_file",
            resolution=resolution,
        ),
        "interleaved_thinking_stream_to_client": _env_to_bool(
            "INTERLEAVED_THINKING_STREAM_TO_CLIENT",
            False,
            env,
            path="backends.interleaved_thinking_stream_to_client",
            resolution=resolution,
        ),
        "interleaved_thinking_regular_turns_remaining": _env_to_int(
            "INTERLEAVED_THINKING_REGULAR_TURNS_REMAINING",
            2,
            env,
            path="backends.interleaved_thinking_regular_turns_remaining",
            resolution=resolution,
        ),
    }

    config["routing"] = {
        "disable_backend_ids": _env_to_bool(
            "DISABLE_ROUTING_WITH_BACKEND_IDS",
            False,
            env,
            path="routing.disable_backend_ids",
            resolution=resolution,
        ),
        "disable_backend_names": _env_to_bool(
            "DISABLE_ROUTING_WITH_BACKEND_NAMES",
            False,
            env,
            path="routing.disable_backend_names",
            resolution=resolution,
        ),
        "disable_model_names": _env_to_bool(
            "DISABLE_ROUTING_WITH_ONLY_MODEL_NAMES",
            False,
            env,
            path="routing.disable_model_names",
            resolution=resolution,
        ),
    }

    config["auxiliary_routing"] = {
        "disable": _env_to_bool(
            "DISABLE_AUXILIARY_ROUTING",
            False,
            env,
            path="auxiliary_routing.disable",
            resolution=resolution,
        ),
    }

    config["compaction"] = {
        "enabled": _env_to_bool(
            "ENABLE_CONTEXT_COMPACTION",
            False,
            env,
            path="compaction.enabled",
            resolution=resolution,
        ),
        "token_threshold": _env_to_int(
            "COMPACTION_MIN_TOKENS",
            100_000,
            env,
            path="compaction.token_threshold",
            resolution=resolution,
        ),
    }

    config["dynamic_compression"] = {
        "enabled": _env_to_bool(
            "ENABLE_DYNAMIC_COMPRESSION",
            False,
            env,
            path="dynamic_compression.enabled",
            resolution=resolution,
        ),
        "level": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_LEVEL",
            "conservative",
            path="dynamic_compression.level",
            resolution=resolution,
        ),
        "max_level": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_MAX_LEVEL",
            "aggressive",
            path="dynamic_compression.max_level",
            resolution=resolution,
        ),
        "min_bytes": _env_to_int(
            "DYNAMIC_COMPRESSION_MIN_BYTES",
            1024,
            env,
            path="dynamic_compression.min_bytes",
            resolution=resolution,
        ),
        "per_output_evaluation_log_level": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_PER_OUTPUT_EVALUATION_LOG_LEVEL",
            "debug",
            path="dynamic_compression.per_output_evaluation_log_level",
            resolution=resolution,
        ),
        "file_detail_include_line_numbers": _env_to_bool(
            "DYNAMIC_COMPRESSION_FILE_DETAIL_INCLUDE_LINE_NUMBERS",
            False,
            env,
            path="dynamic_compression.file_detail_include_line_numbers",
            resolution=resolution,
        ),
        "disable_categories": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_DISABLE_CATEGORIES",
            [],
            path="dynamic_compression.disable_categories",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "disable_methods": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_DISABLE_METHODS",
            [],
            path="dynamic_compression.disable_methods",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "disable_tools": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_DISABLE_TOOLS",
            [],
            path="dynamic_compression.disable_tools",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "disable_command_prefixes": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_DISABLE_COMMAND_PREFIXES",
            [],
            path="dynamic_compression.disable_command_prefixes",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "disable_tool_name_substrings": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_DISABLE_TOOL_NAME_SUBSTRINGS",
            [],
            path="dynamic_compression.disable_tool_name_substrings",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
        "explicit_format_flags": _get_env_value(
            env,
            "DYNAMIC_COMPRESSION_EXPLICIT_FORMAT_FLAGS",
            [],
            path="dynamic_compression.explicit_format_flags",
            resolution=resolution,
            transform=_parse_csv_list,
        ),
    }

    config["identity"] = AppIdentityConfig(
        title=HeaderConfig(
            override_value=_get_env_value(
                env,
                "APP_TITLE",
                None,
                path="identity.title.override_value",
                resolution=resolution,
            ),
            mode=HeaderOverrideMode(
                _get_env_value(
                    env,
                    "APP_TITLE_MODE",
                    "passthrough",
                    path="identity.title.mode",
                    resolution=resolution,
                )
            ),
            default_value="llm-interactive-proxy",
            passthrough_name="x-title",
        ),
        url=HeaderConfig(
            override_value=_get_env_value(
                env,
                "APP_URL",
                None,
                path="identity.url.override_value",
                resolution=resolution,
            ),
            mode=HeaderOverrideMode(
                _get_env_value(
                    env,
                    "APP_URL_MODE",
                    "passthrough",
                    path="identity.url.mode",
                    resolution=resolution,
                )
            ),
            default_value="https://github.com/matdev83/llm-interactive-proxy",
            passthrough_name="http-referer",
        ),
        user_agent=HeaderConfig(
            override_value=_get_env_value(
                env,
                "APP_USER_AGENT",
                None,
                path="identity.user_agent.override_value",
                resolution=resolution,
            ),
            mode=HeaderOverrideMode(
                _get_env_value(
                    env,
                    "APP_USER_AGENT_MODE",
                    "passthrough",
                    path="identity.user_agent.mode",
                    resolution=resolution,
                )
            ),
            default_value="llm-interactive-proxy",
            passthrough_name="user-agent",
        ),
    )

    logger.info(
        "AppConfig.from_env - Determined default_backend: %s",
        config["backends"]["default_backend"],
    )
