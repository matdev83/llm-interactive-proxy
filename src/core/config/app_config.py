from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import ConfigDict

from src.core.config.models import (
    AuthConfig,
    B2BUAConfig,
    BackendConfig,
    BackendSettings,
    BruteForceProtectionConfig,
    CanonicalRequestProcessingConfig,
    CodebuffConfig,
    EditPrecisionConfig,
    EmptyResponseConfig,
    LoggingConfig,
    LogLevel,
    ModelAliasRule,
    PlanningPhaseConfig,
    RewritingConfig,
    RoutingConfig,
    SessionConfig,
    SessionContinuityConfig,
    StreamingSamplerConfig,
    ToolCallReactorConfig,
    UsageTrackingConfig,
    get_openrouter_headers,
)
from src.core.config.models.app_config_model import AppConfigModel
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.config.sources.backend_instances import DEFAULT_BACKEND_INSTANCES_DIR

logger = logging.getLogger(__name__)

# Backward-compatible alias (tests patch this in some places).
BACKEND_INSTANCES_DIR = DEFAULT_BACKEND_INSTANCES_DIR


def _merge_loop_detection_env_session(
    cfg: AppConfig, env: Mapping[str, str]
) -> AppConfig:
    """Sync LOOP_DETECTION_ENABLED into session.streaming_loop_detection_enabled."""
    if "LOOP_DETECTION_ENABLED" not in env:
        return cfg
    from src.loop_detection.config import InternalLoopDetectionConfig

    env_streaming_on = InternalLoopDetectionConfig.from_env_vars(dict(env)).enabled
    return cfg.model_copy(
        update={
            "session": cfg.session.model_copy(
                update={"streaming_loop_detection_enabled": env_streaming_on}
            )
        }
    )


class AppConfig(AppConfigModel):
    """Complete application configuration.

    This class is a thin extension of the pure domain model (`AppConfigModel`)
    that retains legacy convenience methods and factories.
    """

    model_config = ConfigDict(frozen=False, extra="allow", arbitrary_types_allowed=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Backward-compatible initializer.

        Pydantic v2 models accept only keyword arguments; older call sites (and
        tests) sometimes pass a single mapping positionally (e.g. `AppConfig({})`).
        """
        if args:
            if len(args) != 1:
                raise TypeError("AppConfig accepts at most one positional argument")
            if not isinstance(args[0], Mapping):
                raise TypeError(
                    "AppConfig positional argument must be a mapping of fields"
                )
            positional = dict(cast(Mapping[str, Any], args[0]))
            positional.update(kwargs)
            kwargs = positional
        super().__init__(**kwargs)

    def save(self, path: str | Path) -> None:
        """Save the current configuration to a file."""
        p = Path(path)
        data = self.model_dump(mode="json", exclude_none=True)

        for runtime_key in ["app"]:
            if runtime_key in data:
                data[runtime_key] = None

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
            "sso",
            "session",
            "backends",
            "default_backend",
            "reasoning_aliases",
            "model_aliases",
            "sandboxing",
            "codebuff",
            "resilience",
            "usage_tracking",
            "replacement",
            "health_check",
            "usage_window_warmup",
            "failure_handling",
            "routing",
            "dynamic_compression",
            "canonical_request_processing",
            "reasoning_model_token_floor",
            "memory",
            "database",
            "vtc_client_patterns",
            "auto_append_first_prompt_filename",
        }
        data = {k: v for k, v in data.items() if k in allowed_top_keys}

        def _strip_internal_keys(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: _strip_internal_keys(v)
                    for k, v in obj.items()
                    if not k.startswith("_")
                }
            if isinstance(obj, list):
                return [_strip_internal_keys(item) for item in obj]
            return obj

        data = _strip_internal_keys(data)

        if p.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Saving configuration to %s", p)
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
        else:
            with p.open("w", encoding="utf-8") as f:
                f.write(self.model_dump_json(indent=4))

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        resolution: ParameterResolution | None = None,
    ) -> AppConfig:
        """Create AppConfig from environment variables (and instance discovery)."""
        env: Mapping[str, str] = os.environ if environ is None else environ
        res = resolution or ParameterResolution()

        from src.core.config.loading.loader import AppConfigLoader

        loader = AppConfigLoader(backend_instances_dir=BACKEND_INSTANCES_DIR)
        model = loader.load(None, environ=env, resolution=res)
        cfg = cls.model_validate(model.model_dump())
        return _merge_loop_detection_env_session(cfg, env)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dotted key path."""
        keys = key.split(".")
        value: Any = self
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k, default)
                else:
                    value = getattr(value, k, default)
            return value
        except (AttributeError, KeyError, TypeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get configuration value for key '%s': %s",
                    key,
                    e,
                    exc_info=True,
                )
            return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value (legacy convenience).

        .. deprecated::
            ``IConfig.set()`` is deprecated.  Use ``model_copy(update=...)`` on
            the immutable model or mutate runtime state via ``ApplicationState``
            instead.
        """
        warnings.warn(
            "IConfig.set() is deprecated; use model_copy(update=...) or mutate "
            "runtime state via ApplicationState instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        setattr(self, key, value)

    def get_gcp_project_id(self) -> str | None:
        return self.gcp_project_id

    def mutate_backends(
        self,
        updates: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Merge *updates* into ``backends`` and assign the new aggregate.

        ``BackendSettings`` is immutable; tests and migration helpers must not
        assign attributes on ``config.backends`` directly. Pass a mapping for
        hyphenated backend keys (for example ``{"openai-codex": BackendConfig()}``)
        and/or keyword arguments for declared fields such as ``default_backend``.
        """
        merged: dict[str, Any] = {}
        if updates is not None:
            merged.update(dict(updates))
        merged.update(kwargs)
        self.backends = self.backends.model_copy(update=merged)


def load_config(
    config_path: str | Path | None = None,
    *,
    resolution: ParameterResolution | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load configuration from file and environment."""
    env = os.environ if environ is None else environ
    res = resolution or ParameterResolution()

    from src.core.config.loading.loader import AppConfigLoader

    loader = AppConfigLoader(backend_instances_dir=BACKEND_INSTANCES_DIR)
    model = loader.load(config_path, environ=env, resolution=res)

    # Return the legacy concrete type (subclass) for compatibility.
    cfg = AppConfig.model_validate(model.model_dump())
    return _merge_loop_detection_env_session(cfg, env)


__all__ = [
    "AppConfig",
    "AuthConfig",
    "BackendConfig",
    "BackendSettings",
    "B2BUAConfig",
    "BruteForceProtectionConfig",
    "CodebuffConfig",
    "EditPrecisionConfig",
    "EmptyResponseConfig",
    "LogLevel",
    "LoggingConfig",
    "ModelAliasRule",
    "ParameterResolution",
    "ParameterSource",
    "PlanningPhaseConfig",
    "CanonicalRequestProcessingConfig",
    "RewritingConfig",
    "RoutingConfig",
    "SessionConfig",
    "SessionContinuityConfig",
    "StreamingSamplerConfig",
    "ToolCallReactorConfig",
    "UsageTrackingConfig",
    "BACKEND_INSTANCES_DIR",
    "get_openrouter_headers",
    "load_config",
]
