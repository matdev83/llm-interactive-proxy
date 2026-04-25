from __future__ import annotations

import json
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
    get_env_value as _get_env_value,
)
from src.core.config.env.util import (
    to_float as _to_float,
)
from src.core.config.env.util import (
    to_int as _to_int,
)
from src.core.config.parameter_resolution import ParameterResolution


def apply_config_part1b(
    config: dict[str, Any],
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
    planning_overrides: dict[str, Any],
) -> None:
    def _optional_int(value: str) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    config["session"] = {
        "cleanup_enabled": _env_to_bool(
            "SESSION_CLEANUP_ENABLED",
            True,
            env,
            path="session.cleanup_enabled",
            resolution=resolution,
        ),
        "cleanup_interval": _env_to_int(
            "SESSION_CLEANUP_INTERVAL",
            3600,
            env,
            path="session.cleanup_interval",
            resolution=resolution,
        ),
        "max_age": _env_to_int(
            "SESSION_MAX_AGE",
            86400,
            env,
            path="session.max_age",
            resolution=resolution,
        ),
        "default_interactive_mode": _env_to_bool(
            "DEFAULT_INTERACTIVE_MODE",
            True,
            env,
            path="session.default_interactive_mode",
            resolution=resolution,
        ),
        "force_set_project": _env_to_bool(
            "FORCE_SET_PROJECT",
            False,
            env,
            path="session.force_set_project",
            resolution=resolution,
        ),
        "project_dir_resolution_model": _get_env_value(
            env,
            "PROJECT_DIR_RESOLUTION_MODEL",
            None,
            path="session.project_dir_resolution_model",
            resolution=resolution,
        ),
        "project_dir_resolution_mode": _get_env_value(
            env,
            "PROJECT_DIR_RESOLUTION_MODE",
            "hybrid",
            path="session.project_dir_resolution_mode",
            resolution=resolution,
        ),
        "project_dir_resolution_filesystem_mode": _get_env_value(
            env,
            "PROJECT_DIR_RESOLUTION_FILESYSTEM_MODE",
            "auto",
            path="session.project_dir_resolution_filesystem_mode",
            resolution=resolution,
        ),
        "disable_default_openrouter_project_dir_resolution_fallback": _env_to_bool(
            "DISABLE_DEFAULT_OPENROUTER_PROJECT_DIR_RESOLUTION_FALLBACK",
            False,
            env,
            path="session.disable_default_openrouter_project_dir_resolution_fallback",
            resolution=resolution,
        ),
        "tool_call_repair_enabled": _env_to_bool(
            "TOOL_CALL_REPAIR_ENABLED",
            True,
            env,
            path="session.tool_call_repair_enabled",
            resolution=resolution,
        ),
        "tool_call_repair_buffer_cap_bytes": _get_env_value(
            env,
            "TOOL_CALL_REPAIR_BUFFER_CAP_BYTES",
            65536,
            path="session.tool_call_repair_buffer_cap_bytes",
            resolution=resolution,
            transform=lambda value: _to_int(value, 65536),
        ),
        "json_repair_enabled": _env_to_bool(
            "JSON_REPAIR_ENABLED",
            True,
            env,
            path="session.json_repair_enabled",
            resolution=resolution,
        ),
        "json_repair_buffer_cap_bytes": _get_env_value(
            env,
            "JSON_REPAIR_BUFFER_CAP_BYTES",
            65536,
            path="session.json_repair_buffer_cap_bytes",
            resolution=resolution,
            transform=lambda value: _to_int(value, 65536),
        ),
        "json_repair_schema": _get_env_value(
            env,
            "JSON_REPAIR_SCHEMA",
            None,
            path="session.json_repair_schema",
            resolution=resolution,
            transform=lambda value: json.loads(value),
        ),
        "dangerous_command_prevention_enabled": _env_to_bool(
            "DANGEROUS_COMMAND_PREVENTION_ENABLED",
            True,
            env,
            path="session.dangerous_command_prevention_enabled",
            resolution=resolution,
        ),
        "dangerous_command_steering_message": _get_env_value(
            env,
            "DANGEROUS_COMMAND_STEERING_MESSAGE",
            None,
            path="session.dangerous_command_steering_message",
            resolution=resolution,
        ),
        "pytest_full_suite_steering_enabled": _env_to_bool(
            "PYTEST_FULL_SUITE_STEERING_ENABLED",
            False,
            env,
            path="session.pytest_full_suite_steering_enabled",
            resolution=resolution,
        ),
        "pytest_full_suite_steering_message": _get_env_value(
            env,
            "PYTEST_FULL_SUITE_STEERING_MESSAGE",
            None,
            path="session.pytest_full_suite_steering_message",
            resolution=resolution,
        ),
        "cat_file_edits_steering_enabled": _env_to_bool(
            "CAT_FILE_EDITS_STEERING_ENABLED",
            False,
            env,
            path="session.cat_file_edits_steering_enabled",
            resolution=resolution,
        ),
        "cat_file_edits_steering_message": _get_env_value(
            env,
            "CAT_FILE_EDITS_STEERING_MESSAGE",
            None,
            path="session.cat_file_edits_steering_message",
            resolution=resolution,
        ),
        "test_execution_reminder_enabled": _env_to_bool(
            "TEST_EXECUTION_REMINDER_ENABLED",
            False,
            env,
            path="session.test_execution_reminder_enabled",
            resolution=resolution,
        ),
        "test_execution_reminder_message": _get_env_value(
            env,
            "TEST_EXECUTION_REMINDER_MESSAGE",
            None,
            path="session.test_execution_reminder_message",
            resolution=resolution,
        ),
        "fix_think_tags_enabled": _env_to_bool(
            "FIX_THINK_TAGS_ENABLED",
            False,
            env,
            path="session.fix_think_tags_enabled",
            resolution=resolution,
        ),
        "fix_think_tags_streaming_buffer_size": _env_to_int(
            "FIX_THINK_TAGS_STREAMING_BUFFER_SIZE",
            4096,
            env,
            path="session.fix_think_tags_streaming_buffer_size",
            resolution=resolution,
        ),
        "double_ampersand_fixes_for_windows_enabled": _env_to_bool(
            "DOUBLE_AMPERSAND_FIXES_FOR_WINDOWS_ENABLED",
            True,
            env,
            path="session.double_ampersand_fixes_for_windows_enabled",
            resolution=resolution,
        ),
        "auto_continue_removal_enabled": _env_to_bool(
            "AUTO_CONTINUE_REMOVAL_ENABLED",
            True,
            env,
            path="session.auto_continue_removal_enabled",
            resolution=resolution,
        ),
        "planning_phase": {
            "enabled": _env_to_bool(
                "PLANNING_PHASE_ENABLED",
                False,
                env,
                path="session.planning_phase.enabled",
                resolution=resolution,
            ),
            "strong_model": _get_env_value(
                env,
                "PLANNING_PHASE_STRONG_MODEL",
                None,
                path="session.planning_phase.strong_model",
                resolution=resolution,
            ),
            "max_turns": _env_to_int(
                "PLANNING_PHASE_MAX_TURNS",
                10,
                env,
                path="session.planning_phase.max_turns",
                resolution=resolution,
            ),
            "max_file_writes": _env_to_int(
                "PLANNING_PHASE_MAX_FILE_WRITES",
                1,
                env,
                path="session.planning_phase.max_file_writes",
                resolution=resolution,
            ),
            "overrides": planning_overrides,
        },
        "b2bua": {
            "enabled": _env_to_bool(
                "SESSION_B2BUA_ENABLED",
                True,
                env,
                path="session.b2bua.enabled",
                resolution=resolution,
            ),
            "continuity_max_age_seconds": _env_to_int(
                "SESSION_B2BUA_CONTINUITY_MAX_AGE_SECONDS",
                3600,
                env,
                path="session.b2bua.continuity_max_age_seconds",
                resolution=resolution,
            ),
            "continuity_sliding_expiration": _env_to_bool(
                "SESSION_B2BUA_CONTINUITY_SLIDING_EXPIRATION",
                True,
                env,
                path="session.b2bua.continuity_sliding_expiration",
                resolution=resolution,
            ),
            "persistent_mapping_store_enabled": _env_to_bool(
                "SESSION_B2BUA_PERSISTENT_MAPPING_STORE_ENABLED",
                False,
                env,
                path="session.b2bua.persistent_mapping_store_enabled",
                resolution=resolution,
            ),
            "echo_enabled": _env_to_bool(
                "SESSION_B2BUA_ECHO_ENABLED",
                True,
                env,
                path="session.b2bua.echo_enabled",
                resolution=resolution,
            ),
            "echo_header_name": _get_env_value(
                env,
                "SESSION_B2BUA_ECHO_HEADER_NAME",
                "x-b2bua-session-id",
                path="session.b2bua.echo_header_name",
                resolution=resolution,
            ),
            "enable_unsafe_heuristic_session_inference": _env_to_bool(
                "SESSION_B2BUA_ENABLE_UNSAFE_HEURISTIC_SESSION_INFERENCE",
                False,
                env,
                path="session.b2bua.enable_unsafe_heuristic_session_inference",
                resolution=resolution,
            ),
            "deployment_mode": _get_env_value(
                env,
                "SESSION_B2BUA_DEPLOYMENT_MODE",
                "single-process",
                path="session.b2bua.deployment_mode",
                resolution=resolution,
            ),
        },
        "force_reprocess_tool_calls": _env_to_bool(
            "FORCE_REPROCESS_TOOL_CALLS",
            False,
            env,
            path="session.force_reprocess_tool_calls",
            resolution=resolution,
        ),
        "log_skipped_tool_calls": _env_to_bool(
            "LOG_SKIPPED_TOOL_CALLS",
            False,
            env,
            path="session.log_skipped_tool_calls",
            resolution=resolution,
        ),
        "quality_verifier_model": _get_env_value(
            env,
            "QUALITY_VERIFIER_MODEL",
            None,
            path="session.quality_verifier_model",
            resolution=resolution,
        ),
        "quality_verifier_frequency": _env_to_int(
            "QUALITY_VERIFIER_FREQUENCY",
            10,
            env,
            path="session.quality_verifier_frequency",
            resolution=resolution,
        ),
        "quality_verifier_max_history": _get_env_value(
            env,
            "QUALITY_VERIFIER_MAX_HISTORY",
            None,
            path="session.quality_verifier_max_history",
            resolution=resolution,
            transform=_optional_int,
        ),
        "quality_verifier_max_consecutive_failures": _env_to_int(
            "QUALITY_VERIFIER_MAX_CONSECUTIVE_FAILURES",
            5,
            env,
            path="session.quality_verifier_max_consecutive_failures",
            resolution=resolution,
        ),
        "quality_verifier_cooldown_seconds": _env_to_int(
            "QUALITY_VERIFIER_COOLDOWN_SECONDS",
            300,
            env,
            path="session.quality_verifier_cooldown_seconds",
            resolution=resolution,
        ),
        "quality_verifier_ttft_timeout_seconds": _env_to_float(
            "QUALITY_VERIFIER_TTFT_TIMEOUT_SECONDS",
            30.0,
            env,
            path="session.quality_verifier_ttft_timeout_seconds",
            resolution=resolution,
        ),
        "quality_verifier_tool_followup_weight": _env_to_float(
            "QUALITY_VERIFIER_TOOL_FOLLOWUP_WEIGHT",
            0.2,
            env,
            path="session.quality_verifier_tool_followup_weight",
            resolution=resolution,
        ),
        "streaming_sampler": {
            "enabled": _env_to_bool(
                "STREAMING_SAMPLER_ENABLED",
                True,
                env,
                path="session.streaming_sampler.enabled",
                resolution=resolution,
            ),
            "sample_rate": _env_to_float(
                "STREAMING_SAMPLER_RATE",
                0.01,
                env,
                path="session.streaming_sampler.sample_rate",
                resolution=resolution,
            ),
            "max_samples": _env_to_int(
                "STREAMING_SAMPLER_MAX_SAMPLES",
                100,
                env,
                path="session.streaming_sampler.max_samples",
                resolution=resolution,
            ),
        },
        "tool_call_reactor": {
            "binary_file_edit_steering_enabled": not _env_to_bool(
                "DISABLE_BINARY_FILE_EDIT_STEERING",
                False,
                env,
                path="session.tool_call_reactor.binary_file_edit_steering_enabled",
                resolution=resolution,
            ),
            "binary_file_edit_steering_message": _get_env_value(
                env,
                "BINARY_FILE_EDIT_STEERING_MESSAGE",
                None,
                path="session.tool_call_reactor.binary_file_edit_steering_message",
                resolution=resolution,
            ),
        },
    }

    config["logging"] = {
        "level": _get_env_value(
            env,
            "LOG_LEVEL",
            "INFO",
            path="logging.level",
            resolution=resolution,
        ),
        "use_colors": _env_to_bool(
            "LOG_USE_COLORS",
            False,
            env,
            path="logging.use_colors",
            resolution=resolution,
        ),
        "console_stream": _get_env_value(
            env,
            "LOG_STREAM",
            "stderr",
            path="logging.console_stream",
            resolution=resolution,
            transform=lambda value: str(value or "").strip().lower(),
        ),
        "request_logging": _env_to_bool(
            "REQUEST_LOGGING",
            False,
            env,
            path="logging.request_logging",
            resolution=resolution,
        ),
        "response_logging": _env_to_bool(
            "RESPONSE_LOGGING",
            False,
            env,
            path="logging.response_logging",
            resolution=resolution,
        ),
        "log_file": _get_env_value(
            env,
            "LOG_FILE",
            None,
            path="logging.log_file",
            resolution=resolution,
        ),
        "capture_file": _get_env_value(
            env,
            "CAPTURE_FILE",
            None,
            path="logging.capture_file",
            resolution=resolution,
        ),
        "capture_max_bytes": _get_env_value(
            env,
            "CAPTURE_MAX_BYTES",
            None,
            path="logging.capture_max_bytes",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        ),
        "capture_truncate_bytes": _get_env_value(
            env,
            "CAPTURE_TRUNCATE_BYTES",
            None,
            path="logging.capture_truncate_bytes",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        ),
        "capture_max_files": _get_env_value(
            env,
            "CAPTURE_MAX_FILES",
            None,
            path="logging.capture_max_files",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0),
        ),
        "capture_rotate_interval_seconds": _get_env_value(
            env,
            "CAPTURE_ROTATE_INTERVAL_SECONDS",
            86400,
            path="logging.capture_rotate_interval_seconds",
            resolution=resolution,
            transform=lambda value: _to_int(value, 86400),
        ),
        "capture_total_max_bytes": _get_env_value(
            env,
            "CAPTURE_TOTAL_MAX_BYTES",
            104857600,
            path="logging.capture_total_max_bytes",
            resolution=resolution,
            transform=lambda value: _to_int(value, 104857600),
        ),
        "capture_buffer_size": _get_env_value(
            env,
            "CAPTURE_BUFFER_SIZE",
            65536,
            path="logging.capture_buffer_size",
            resolution=resolution,
            transform=lambda value: _to_int(value, 65536),
        ),
        "capture_flush_interval": _get_env_value(
            env,
            "CAPTURE_FLUSH_INTERVAL",
            1.0,
            path="logging.capture_flush_interval",
            resolution=resolution,
            transform=lambda value: _to_float(value, 1.0),
        ),
        "capture_max_entries_per_flush": _get_env_value(
            env,
            "CAPTURE_MAX_ENTRIES_PER_FLUSH",
            100,
            path="logging.capture_max_entries_per_flush",
            resolution=resolution,
            transform=lambda value: _to_int(value, 100),
        ),
        "cbor_capture_flush_interval": _get_env_value(
            env,
            "CBOR_CAPTURE_FLUSH_INTERVAL",
            1.0,
            path="logging.cbor_capture_flush_interval",
            resolution=resolution,
            transform=lambda value: _to_float(value, 1.0),
        ),
    }

    config["empty_response"] = {
        "enabled": _env_to_bool(
            "EMPTY_RESPONSE_HANDLING_ENABLED",
            True,
            env,
            path="empty_response.enabled",
            resolution=resolution,
        ),
        "max_retries": _env_to_int(
            "EMPTY_RESPONSE_MAX_RETRIES",
            1,
            env,
            path="empty_response.max_retries",
            resolution=resolution,
        ),
        "count_reasoning_for_empty_stream": _env_to_bool(
            "EMPTY_RESPONSE_COUNT_REASONING_FOR_EMPTY_STREAM",
            True,
            env,
            path="empty_response.count_reasoning_for_empty_stream",
            resolution=resolution,
        ),
    }

    config["edit_precision"] = {
        "enabled": _env_to_bool(
            "EDIT_PRECISION_ENABLED",
            True,
            env,
            path="edit_precision.enabled",
            resolution=resolution,
        ),
        "temperature": _env_to_float(
            "EDIT_PRECISION_TEMPERATURE",
            0.1,
            env,
            path="edit_precision.temperature",
            resolution=resolution,
        ),
        "min_top_p": _env_to_float(
            "EDIT_PRECISION_MIN_TOP_P",
            0.3,
            env,
            path="edit_precision.min_top_p",
            resolution=resolution,
        ),
        "override_top_p": _env_to_bool(
            "EDIT_PRECISION_OVERRIDE_TOP_P",
            False,
            env,
            path="edit_precision.override_top_p",
            resolution=resolution,
        ),
        "override_top_k": _env_to_bool(
            "EDIT_PRECISION_OVERRIDE_TOP_K",
            False,
            env,
            path="edit_precision.override_top_k",
            resolution=resolution,
        ),
        "target_top_k": _get_env_value(
            env,
            "EDIT_PRECISION_TARGET_TOP_K",
            None,
            path="edit_precision.target_top_k",
            resolution=resolution,
            transform=lambda value: _to_int(value, 0) or None,
        ),
        "exclude_agents_regex": _get_env_value(
            env,
            "EDIT_PRECISION_EXCLUDE_AGENTS_REGEX",
            None,
            path="edit_precision.exclude_agents_regex",
            resolution=resolution,
        ),
    }

    config["rewriting"] = {
        "enabled": _env_to_bool(
            "REWRITING_ENABLED",
            False,
            env,
            path="rewriting.enabled",
            resolution=resolution,
        ),
        "config_path": _get_env_value(
            env,
            "REWRITING_CONFIG_PATH",
            "config/replacements",
            path="rewriting.config_path",
            resolution=resolution,
        ),
    }
