from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict, Field

from src.core.config._app_config_models import (
    AuthConfig,
    BackendConfig,
    BackendSettings,
    BruteForceProtectionConfig,
    EditPrecisionConfig,
    EmptyResponseConfig,
    LogLevel,
    LoggingConfig,
    ModelAliasRule,
    PlanningPhaseConfig,
    RewritingConfig,
    SessionConfig,
    SessionContinuityConfig,
    ToolCallReactorConfig,
)
from src.core.config._app_config_utils import (
    _collect_api_keys_from_env,
    _env_to_bool,
    _env_to_float,
    _env_to_int,
    _flatten_dict,
    _get_api_keys_from_env,
    _get_by_path,
    _get_env_value,
    _merge_dicts,
    _process_api_keys,
    _set_by_path,
    _to_float,
    _to_int,
    get_openrouter_headers,
    load_config,
)
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.header_config import (
    HeaderConfig,
    HeaderOverrideMode,
)
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.model_bases import DomainModel
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)
 

class AppConfig(DomainModel, IConfig):
    """Complete application configuration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    host: str = "127.0.0.1"  # Default to localhost for security
    port: int = 8000
    anthropic_port: int | None = None  # Will be set to port + 1 if not provided
    proxy_timeout: int = 120
    command_prefix: str = "!/"
    strict_command_detection: bool = False
    context_window_override: int | None = None  # Override context window for all models
    gcp_project_id: str | None = None
    gemini_credentials_path: str | None = None
    disable_health_checks: bool = False

    # Rate limit settings
    default_rate_limit: int = 60
    default_rate_window: int = 60

    # Backend settings
    backends: BackendSettings = Field(default_factory=BackendSettings)
    model_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)
    failover_routes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # No nested class references - use direct imports instead

    # Identity settings
    identity: AppIdentityConfig = Field(default_factory=AppIdentityConfig)

    # Auth settings
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Session settings
    session: SessionConfig = Field(default_factory=SessionConfig)

    # Logging settings
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Empty response handling settings
    empty_response: EmptyResponseConfig = Field(default_factory=EmptyResponseConfig)

    # Edit-precision tuning settings
    edit_precision: EditPrecisionConfig = Field(default_factory=EditPrecisionConfig)

    # Rewriting settings
    rewriting: RewritingConfig = Field(default_factory=RewritingConfig)
    assessment: AssessmentConfig = Field(default_factory=AssessmentConfig)

    # Reasoning aliases settings
    reasoning_aliases: ReasoningAliasesConfig = Field(
        default_factory=lambda: ReasoningAliasesConfig(reasoning_alias_settings=[])
    )

    # Model name rewrite rules
    model_aliases: list[ModelAliasRule] = Field(default_factory=list)

    # Sandboxing settings
    sandboxing: SandboxingConfiguration = Field(default_factory=SandboxingConfiguration)

    # FastAPI app instance
    app: Any = None

    def model_is_functional(self, model_id: str) -> bool:
        """Check if a model is available in any functional backend."""
        return self.backends.model_is_functional(model_id)

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        p = Path(path)
        data = self.model_dump(mode="json", exclude_none=True)
        # Normalize structure to match schema expectations
        # - default_backend must be at top-level (already present)
        # - Remove runtime-only fields that are not part of schema or can cause validation errors
        for runtime_key in ["app"]:
            if runtime_key in data:
                data[runtime_key] = None
        # Filter out unsupported top-level keys (schema has additionalProperties: false)
        allowed_top_keys = {
            "host",
            "port",
            "anthropic_port",
            "proxy_timeout",
            "command_prefix",
            "strict_command_detection",
            "context_window_override",
            "default_rate_limit",
            "default_rate_window",
            "model_defaults",
            "failover_routes",
            "identity",
            "empty_response",
            "edit_precision",
            "rewriting",
            "app",
            "logging",
            "auth",
            "session",
            "backends",
            "default_backend",
            "reasoning_aliases",
            "model_aliases",
            "sandboxing",
        }
        data = {k: v for k, v in data.items() if k in allowed_top_keys}
        # Ensure nested sections only include serializable primitives
        # (model_dump already handles pydantic models)
        if p.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            logger.debug(f"Saving configuration to {p}: {data}")
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
        else:
            # Legacy: still allow JSON save if requested by extension
            with p.open("w", encoding="utf-8") as f:
                f.write(self.model_dump_json(indent=4))

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        resolution: ParameterResolution | None = None,
    ) -> AppConfig:
        """Create AppConfig from environment variables.

        Returns:
            AppConfig instance
        """
        env: Mapping[str, str] = os.environ if environ is None else environ

        # Build configuration from environment
        config: dict[str, Any] = {
            # Server settings
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
            "host": _get_env_value(
                env,
                "APP_HOST",
                "127.0.0.1",  # Default to localhost for security
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

        if not config.get("anthropic_port"):
            config["anthropic_port"] = int(config["port"]) + 1
            if resolution is not None:
                resolution.record(
                    "anthropic_port",
                    config["anthropic_port"],
                    ParameterSource.DERIVED,
                    origin="port+1",
                )

        # After populating auth config, if disable_auth is true, clear api_keys
        auth_config: dict[str, Any] = config["auth"]
        if isinstance(auth_config, dict) and auth_config.get("disable_auth"):
            auth_config["api_keys"] = []

        # Add session, logging, and backend config
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
            "pytest_compression_enabled": _env_to_bool(
                "PYTEST_COMPRESSION_ENABLED",
                True,
                env,
                path="session.pytest_compression_enabled",
                resolution=resolution,
            ),
            "pytest_compression_min_lines": _env_to_int(
                "PYTEST_COMPRESSION_MIN_LINES",
                30,
                env,
                path="session.pytest_compression_min_lines",
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
        }

        config["logging"] = {
            "level": _get_env_value(
                env,
                "LOG_LEVEL",
                "INFO",
                path="logging.level",
                resolution=resolution,
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
        }

        # Edit precision settings
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

        # Assessment configuration from environment
        config["assessment"] = {
            "enabled": _env_to_bool(
                "LLM_ASSESSMENT_ENABLED",
                False,
                env,
                path="assessment.enabled",
                resolution=resolution,
            ),
            "turn_threshold": _env_to_int(
                "LLM_ASSESSMENT_TURN_THRESHOLD",
                30,
                env,
                path="assessment.turn_threshold",
                resolution=resolution,
            ),
            "confidence_threshold": _env_to_float(
                "LLM_ASSESSMENT_CONFIDENCE_THRESHOLD",
                0.9,
                env,
                path="assessment.confidence_threshold",
                resolution=resolution,
            ),
            "backend": _get_env_value(
                env,
                "LLM_ASSESSMENT_BACKEND",
                "openai",  # Default backend
                path="assessment.backend",
                resolution=resolution,
            ),
            "model": _get_env_value(
                env,
                "LLM_ASSESSMENT_MODEL",
                "gpt-4o-mini",  # Default model
                path="assessment.model",
                resolution=resolution,
            ),
            "history_window": _env_to_int(
                "LLM_ASSESSMENT_HISTORY_WINDOW",
                20,
                env,
                path="assessment.history_window",
                resolution=resolution,
            ),
        }

        # Sandboxing configuration from environment
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

        # Model aliases configuration from environment
        model_aliases_env = env.get("MODEL_ALIASES")
        if model_aliases_env:
            try:
                alias_data = json.loads(model_aliases_env)
                if isinstance(alias_data, list):
                    config["model_aliases"] = [
                        {"pattern": item["pattern"], "replacement": item["replacement"]}
                        for item in alias_data
                        if isinstance(item, dict)
                        and "pattern" in item
                        and "replacement" in item
                    ]
                    if resolution is not None:
                        resolution.record(
                            "model_aliases",
                            config["model_aliases"],
                            ParameterSource.ENVIRONMENT,
                            origin="MODEL_ALIASES",
                        )
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    f"Invalid MODEL_ALIASES environment variable format: {e}"
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

        # Log the determined default_backend
        logger.info(
            f"AppConfig.from_env - Determined default_backend: {config['backends']['default_backend']}"
        )

        # Extract backend configurations from environment
        config_backends: dict[str, Any] = config["backends"]
        assert isinstance(config_backends, dict)

        # Collect and assign API keys for specific backends
        openrouter_keys = _collect_api_keys_from_env(
            "OPENROUTER_API_KEY", env, resolution
        )
        if openrouter_keys:
            config_backends["openrouter"] = config_backends.get("openrouter", {})
            config_backends["openrouter"]["api_key"] = list(openrouter_keys.values())
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
                    origin="OPENROUTER_API_KEY*",
                )

        gemini_keys: dict[str, str] = _collect_api_keys_from_env(
            "GEMINI_API_KEY", env, resolution
        )
        if gemini_keys:
            config_backends["gemini"] = config_backends.get("gemini", {})
            config_backends["gemini"]["api_key"] = list(gemini_keys.values())
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
                    origin="GEMINI_API_KEY*",
                )

        anthropic_keys: dict[str, str] = _collect_api_keys_from_env(
            "ANTHROPIC_API_KEY", env, resolution
        )
        if anthropic_keys:
            config_backends["anthropic"] = config_backends.get("anthropic", {})
            config_backends["anthropic"]["api_key"] = list(anthropic_keys.values())
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
                    origin="ANTHROPIC_API_KEY*",
                )

        zai_keys: dict[str, str] = _collect_api_keys_from_env(
            "ZAI_API_KEY", env, resolution
        )
        if zai_keys:
            config_backends["zai"] = config_backends.get("zai", {})
            config_backends["zai"]["api_key"] = list(zai_keys.values())
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
                    origin="ZAI_API_KEY*",
                )

        openai_keys: dict[str, str] = _collect_api_keys_from_env(
            "OPENAI_API_KEY", env, resolution
        )
        if openai_keys:
            config_backends["openai"] = config_backends.get("openai", {})
            config_backends["openai"]["api_key"] = list(openai_keys.values())
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
                    origin="OPENAI_API_KEY*",
                )

        minimax_keys: dict[str, str] = _collect_api_keys_from_env(
            "MINIMAX_API_KEY", env, resolution
        )
        if minimax_keys:
            config_backends["minimax"] = config_backends.get("minimax", {})
            config_backends["minimax"]["api_key"] = list(minimax_keys.values())
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
                    origin="MINIMAX_API_KEY*",
                )

        # Handle default backend if it's not explicitly configured above
        default_backend_type: str = str(
            config["backends"].get("default_backend", "openai")
        )
        if default_backend_type not in config_backends:
            # If the default backend is not explicitly configured, ensure it has a basic config
            config_backends[default_backend_type] = config_backends.get(
                default_backend_type, {}
            )
            # Add a dummy API key if running in test environment and no API key is present
            if env.get("PYTEST_CURRENT_TEST") and (
                not config_backends[default_backend_type]
                or not config_backends[default_backend_type].get("api_key")
            ):
                config_backends[default_backend_type]["api_key"] = [
                    f"test-key-{default_backend_type}"
                ]
                logger.info(
                    f"Added test API key for default backend {default_backend_type}"
                )

        return cls(**config)  # type: ignore

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key."""
        # Split the key by dots to handle nested attributes
        keys = key.split(".")
        value: Any = self

        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k, default)
                else:
                    value = getattr(value, k, default)
            return value
        except Exception:
            return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value."""
        # For simplicity, we'll only handle top-level attributes
        # In a more complex implementation, we might want to handle nested attributes
        setattr(self, key, value)

    def get_gcp_project_id(self) -> str | None:
        """Return the GCP Project ID."""
        return self.gcp_project_id
