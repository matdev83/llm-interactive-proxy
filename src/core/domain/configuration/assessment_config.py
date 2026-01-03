"""
Configuration for LLM-based conversation assessment system.

This module defines the configuration structure for the assessment system,
replicating the constants and behavior from gemini-cli's loopDetectionService.ts.

Reference: dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts (lines 33-55)
"""

import contextlib
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssessmentConfig:
    """
    Configuration for LLM assessment system, mirroring gemini-cli constants.

    Constants replicated from gemini-cli:
    - LLM_CHECK_AFTER_TURNS = 30
    - LLM_LOOP_CHECK_HISTORY_COUNT = 20
    - DEFAULT_LLM_CHECK_INTERVAL = 3
    - MIN_LLM_CHECK_INTERVAL = 5
    - MAX_LLM_CHECK_INTERVAL = 15
    """

    enabled: bool = False
    turn_threshold: int = 30  # LLM_CHECK_AFTER_TURNS
    confidence_threshold: float = 0.9
    history_window: int = 20  # LLM_LOOP_CHECK_HISTORY_COUNT
    min_interval: int = 5  # MIN_LLM_CHECK_INTERVAL
    max_interval: int = 15  # MAX_LLM_CHECK_INTERVAL
    default_interval: int = 3  # DEFAULT_LLM_CHECK_INTERVAL
    backend: str = "openai"  # Default backend
    model: str = "gpt-4o-mini"  # Default model
    disable_for_sessions: list[str] = field(default_factory=list)
    _env_set_fields: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def from_cli_args(cls, args) -> "AssessmentConfig":
        """Create configuration from CLI arguments with highest precedence."""
        config = cls()

        # Support the shorter attribute name for compatibility (check first)
        if hasattr(args, "llm_assessment_enabled") and not hasattr(args, "_mock_name"):
            # Handle different types for enabled flag
            if isinstance(args.llm_assessment_enabled, bool):
                config.enabled = args.llm_assessment_enabled
            elif isinstance(args.llm_assessment_enabled, str):
                if args.llm_assessment_enabled.lower() in ("true", "1", "yes", "on"):
                    config.enabled = True
                elif args.llm_assessment_enabled.lower() in ("false", "0", "no", "off"):
                    config.enabled = False
                else:
                    # Invalid string, keep default
                    pass
            else:
                # Invalid type, keep default
                pass
        elif hasattr(args, "llm_loop_assessment_enabled") and not hasattr(
            args, "_mock_name"
        ):
            # Handle different types for enabled flag
            if isinstance(args.llm_loop_assessment_enabled, bool):
                config.enabled = args.llm_loop_assessment_enabled
            elif isinstance(args.llm_loop_assessment_enabled, str):
                if args.llm_loop_assessment_enabled.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                ):
                    config.enabled = True
                elif args.llm_loop_assessment_enabled.lower() in (
                    "false",
                    "0",
                    "no",
                    "off",
                ):
                    config.enabled = False
                else:
                    # Invalid string, keep default
                    pass
            else:
                # Invalid type, keep default
                pass
        elif hasattr(args, "enable_llm_assessment") and args.enable_llm_assessment:
            config.enabled = True

        if (
            hasattr(args, "llm_assessment_turn_threshold")
            and args.llm_assessment_turn_threshold is not None
            and isinstance(args.llm_assessment_turn_threshold, int)
            and args.llm_assessment_turn_threshold >= 1
        ):
            config.turn_threshold = args.llm_assessment_turn_threshold

        if (
            hasattr(args, "llm_assessment_confidence_threshold")
            and args.llm_assessment_confidence_threshold is not None
            and isinstance(args.llm_assessment_confidence_threshold, int | float)
            and 0.0 <= args.llm_assessment_confidence_threshold <= 1.0
        ):
            config.confidence_threshold = args.llm_assessment_confidence_threshold

        if (
            hasattr(args, "llm_assessment_backend")
            and args.llm_assessment_backend
            and isinstance(args.llm_assessment_backend, str)
            and args.llm_assessment_backend.strip()
        ):
            backend_value = args.llm_assessment_backend.strip()
            # Only accept known valid backends
            if backend_value in ["openai", "anthropic", "gemini"]:
                config.backend = backend_value

        if (
            hasattr(args, "llm_assessment_model")
            and args.llm_assessment_model
            and isinstance(args.llm_assessment_model, str)
            and args.llm_assessment_model.strip()
        ):
            model_str = args.llm_assessment_model.strip()
            # Check if model contains backend:model format
            if ":" in model_str:
                backend, model = model_str.split(":", 1)
                backend = backend.strip()
                model = model.strip()
                # Only accept known valid backends
                if backend in ["openai", "anthropic", "gemini"]:
                    config.backend = backend
                config.model = model
            else:
                config.model = model_str

        if (
            hasattr(args, "llm_assessment_history_window")
            and args.llm_assessment_history_window is not None
            and not hasattr(args.llm_assessment_history_window, "_mock_name")
        ):
            config.history_window = args.llm_assessment_history_window

        return config

    @classmethod
    def from_env_vars(cls) -> "AssessmentConfig":
        """Create configuration from environment variables."""
        config = cls()

        # Track which values were actually set vs just defaults
        config._env_set_fields = set()

        enabled = os.getenv("LLM_ASSESSMENT_ENABLED", "").lower()
        if enabled:
            if enabled in ("true", "1", "yes", "on"):
                config.enabled = True
                config._env_set_fields.add("enabled")
            elif enabled in ("false", "0", "no", "off"):
                config.enabled = False
                config._env_set_fields.add("enabled")

        if threshold := os.getenv("LLM_ASSESSMENT_TURN_THRESHOLD"):
            with contextlib.suppress(ValueError):
                # Keep default value if env var is not a valid integer
                config.turn_threshold = int(threshold)
                config._env_set_fields.add("turn_threshold")

        if confidence := os.getenv("LLM_ASSESSMENT_CONFIDENCE_THRESHOLD"):
            with contextlib.suppress(ValueError):
                # Keep default value if env var is not a valid float
                config.confidence_threshold = float(confidence)
                config._env_set_fields.add("confidence_threshold")

        if backend := os.getenv("LLM_ASSESSMENT_BACKEND"):
            backend_value = backend.strip()
            # Only accept known valid backends
            if backend_value in ["openai", "anthropic", "gemini"]:
                config.backend = backend_value
                config._env_set_fields.add("backend")

        if model := os.getenv("LLM_ASSESSMENT_MODEL"):
            config.model = model.strip()
            config._env_set_fields.add("model")

        if window := os.getenv("LLM_ASSESSMENT_HISTORY_WINDOW"):
            try:
                config.history_window = int(window)
                config._env_set_fields.add("history_window")
            except ValueError:
                pass  # Keep default

        if min_interval := os.getenv("LLM_ASSESSMENT_MIN_INTERVAL"):
            try:
                config.min_interval = int(min_interval)
                config._env_set_fields.add("min_interval")
            except ValueError:
                pass  # Keep default

        if max_interval := os.getenv("LLM_ASSESSMENT_MAX_INTERVAL"):
            try:
                config.max_interval = int(max_interval)
                config._env_set_fields.add("max_interval")
            except ValueError:
                pass  # Keep default

        return config

    @classmethod
    def from_yaml(cls, yaml_config: dict[str, Any]) -> "AssessmentConfig":
        """Create configuration from YAML configuration."""
        config = cls()

        if "llm_assessment" not in yaml_config:
            return config

        assessment_config = yaml_config["llm_assessment"]

        if "enabled" in assessment_config:
            enabled_value = assessment_config["enabled"]
            # Only accept boolean types
            if isinstance(enabled_value, bool):
                config.enabled = enabled_value

        if "turn_threshold" in assessment_config:
            with contextlib.suppress(ValueError, TypeError):
                config.turn_threshold = int(assessment_config["turn_threshold"])

        if "confidence_threshold" in assessment_config:
            with contextlib.suppress(ValueError, TypeError):
                config.confidence_threshold = float(
                    assessment_config["confidence_threshold"]
                )

        if "backend" in assessment_config:
            backend_value = str(assessment_config["backend"]).strip()
            # Only accept known valid backends
            if backend_value in ["openai", "anthropic", "gemini"]:
                config.backend = backend_value

        if "model" in assessment_config:
            model_value = assessment_config["model"]
            # Only accept string types
            if isinstance(model_value, str):
                config.model = model_value.strip()

        if "history_window" in assessment_config:
            with contextlib.suppress(ValueError, TypeError):
                config.history_window = int(assessment_config["history_window"])

        # Handle min_interval directly and within intervals
        if "min_interval" in assessment_config:
            with contextlib.suppress(ValueError, TypeError):
                config.min_interval = int(assessment_config["min_interval"])

        if "max_interval" in assessment_config:
            with contextlib.suppress(ValueError, TypeError):
                config.max_interval = int(assessment_config["max_interval"])

        if "intervals" in assessment_config:
            intervals = assessment_config["intervals"]
            if "min" in intervals:
                with contextlib.suppress(ValueError, TypeError):
                    config.min_interval = int(intervals["min"])
            if "max" in intervals:
                with contextlib.suppress(ValueError, TypeError):
                    config.max_interval = int(intervals["max"])
            if "default" in intervals:
                with contextlib.suppress(ValueError, TypeError):
                    config.default_interval = int(intervals["default"])

        if "disable_for_sessions" in assessment_config:
            config.disable_for_sessions = list(
                assessment_config["disable_for_sessions"]
            )

        return config

    @classmethod
    def merge_configs(
        cls,
        cli_config: "AssessmentConfig",
        env_config: "AssessmentConfig",
        yaml_config: "AssessmentConfig",
    ) -> "AssessmentConfig":
        """
        Merge configurations with precedence: CLI > ENV > YAML > defaults.

        This follows the same precedence pattern used throughout the proxy.
        """
        # Start with YAML (lowest precedence)
        merged = AssessmentConfig(
            enabled=yaml_config.enabled,
            turn_threshold=yaml_config.turn_threshold,
            confidence_threshold=yaml_config.confidence_threshold,
            history_window=yaml_config.history_window,
            min_interval=yaml_config.min_interval,
            max_interval=yaml_config.max_interval,
            default_interval=yaml_config.default_interval,
            backend=yaml_config.backend,
            model=yaml_config.model,
            disable_for_sessions=yaml_config.disable_for_sessions.copy(),
        )

        # Override with CLI (highest precedence)
        default_config = cls()
        if cli_config.enabled != default_config.enabled:
            merged.enabled = cli_config.enabled
        if cli_config.turn_threshold != default_config.turn_threshold:
            merged.turn_threshold = cli_config.turn_threshold
        if cli_config.confidence_threshold != default_config.confidence_threshold:
            merged.confidence_threshold = cli_config.confidence_threshold
        if cli_config.backend != default_config.backend:
            merged.backend = cli_config.backend
        if cli_config.model != default_config.model:
            merged.model = cli_config.model
        if cli_config.history_window != default_config.history_window:
            merged.history_window = cli_config.history_window
        if cli_config.min_interval != default_config.min_interval:
            merged.min_interval = cli_config.min_interval
        if cli_config.max_interval != default_config.max_interval:
            merged.max_interval = cli_config.max_interval
        if cli_config.default_interval != default_config.default_interval:
            merged.default_interval = cli_config.default_interval

        # Override with ENV (medium precedence) - only if CLI wasn't set
        # Only override if the env config actually has the field set
        if "enabled" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.enabled == default_config.enabled
        ):  # Only use ENV if CLI didn't override
            merged.enabled = env_config.enabled
        if "turn_threshold" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.turn_threshold == default_config.turn_threshold
        ):
            merged.turn_threshold = env_config.turn_threshold
        if "confidence_threshold" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.confidence_threshold == default_config.confidence_threshold
        ):
            merged.confidence_threshold = env_config.confidence_threshold
        if "backend" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.backend == default_config.backend
        ):
            merged.backend = env_config.backend
        if "model" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.model == default_config.model
        ):
            merged.model = env_config.model
        if "history_window" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.history_window == default_config.history_window
        ):
            merged.history_window = env_config.history_window
        if "min_interval" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.min_interval == default_config.min_interval
        ):
            merged.min_interval = env_config.min_interval
        if "max_interval" in getattr(env_config, "_env_set_fields", set()) and (
            cli_config.max_interval == default_config.max_interval
        ):
            merged.max_interval = env_config.max_interval

        return merged

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if self.turn_threshold < 1:
            errors.append("turn_threshold must be >= 1")

        if not 0.0 <= self.confidence_threshold <= 1.0:
            errors.append("confidence_threshold must be between 0.0 and 1.0")

        if self.history_window < 1:
            errors.append("history_window must be >= 1")

        if self.min_interval < 1:
            errors.append("min_interval must be >= 1")

        if self.max_interval < self.min_interval:
            errors.append("max_interval must be >= min_interval")

        if self.default_interval < 1:
            errors.append("default_interval must be >= 1")

        if self.enabled and not self.backend:
            errors.append("backend must be specified when assessment is enabled")

        if self.enabled and not self.model:
            errors.append("model must be specified when assessment is enabled")

        return errors

    def is_session_disabled(self, session_id: str) -> bool:
        """Check if assessment is disabled for a specific session."""
        return session_id in self.disable_for_sessions
