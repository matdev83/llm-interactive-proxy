"""
Semantic validation for configuration files.

This module provides validation beyond basic JSON schema validation,
checking for logical consistency and common configuration mistakes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.common.exceptions import ConfigurationError
from src.core.common.session_continuity_warnings import topic_similarity_enabled_warning
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


class ConfigurationValidator:
    """Validates configuration for semantic correctness."""

    def __init__(self, config_data: dict[str, Any], config_path: str | Path) -> None:
        self.config_data = config_data
        self.config_path = str(config_path)
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self) -> None:
        """Run all semantic validations."""
        self._validate_wire_capture_config()
        self._validate_logging_config()
        self._validate_backend_config()
        self._validate_end_of_session_config()
        self._validate_session_continuity_config()

        if self.errors:
            raise ConfigurationError(
                message="Configuration validation failed",
                details={
                    "path": self.config_path,
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "recovery_instructions": self._get_recovery_instructions(),
                },
            )

        if self.warnings:
            for warning in self.warnings:
                logger.warning("Configuration warning: %s", warning)

    def _validate_wire_capture_config(self) -> None:
        """Validate wire capture configuration."""
        logging_config = self.config_data.get("logging", {})

        log_file = logging_config.get("log_file")
        capture_file = logging_config.get("capture_file")

        # Check for common mistake: using log_file for wire capture
        if log_file and "wire_capture" in str(log_file).lower():
            self.errors.append(
                f"logging.log_file is set to '{log_file}' which appears to be intended for wire capture. "
                f"Use 'logging.capture_file' instead for wire-level HTTP capture. "
                f"'log_file' is for general application logs."
            )

        # Check for conflicting file paths
        if log_file and capture_file and log_file == capture_file:
            self.errors.append(
                f"logging.log_file and logging.capture_file cannot point to the same file: '{log_file}'. "
                f"These serve different purposes and must use separate files."
            )

        # Validate capture file configuration consistency
        if capture_file:
            capture_options = [
                "capture_max_bytes",
                "capture_truncate_bytes",
                "capture_max_files",
                "capture_rotate_interval_seconds",
                "capture_total_max_bytes",
            ]

            # Check if capture options are set without capture_file
            for option in capture_options:
                if logging_config.get(option) is not None:
                    # This is actually OK - capture_file enables the options
                    break
        else:
            # Check if capture options are set without capture_file
            capture_options_set: list[str] = []
            for option in [
                "capture_max_bytes",
                "capture_truncate_bytes",
                "capture_max_files",
            ]:
                if logging_config.get(option) is not None:
                    capture_options_set.append(option)

            if capture_options_set:
                self.warnings.append(
                    f"Wire capture options {capture_options_set} are set but logging.capture_file is not configured. "
                    f"These options will have no effect without capture_file."
                )

    def _validate_logging_config(self) -> None:
        """Validate general logging configuration."""
        logging_config = self.config_data.get("logging", {})

        # Check log level
        level = logging_config.get("level")
        if level and level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            self.errors.append(
                f"logging.level '{level}' is invalid. "
                f"Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )

    def _validate_backend_config(self) -> None:
        """Validate backend configuration."""
        backends_config = self.config_data.get("backends", {})
        default_backend = backends_config.get("default_backend")

        if default_backend and default_backend not in backends_config:
            self.warnings.append(
                f"backends.default_backend is set to '{default_backend}' but no configuration "
                f"exists for this backend. Ensure the backend is properly configured."
            )

    def _validate_session_continuity_config(self) -> None:
        session_cfg = self.config_data.get("session")
        if not isinstance(session_cfg, dict):
            return

        continuity_cfg = session_cfg.get("session_continuity")
        if not isinstance(continuity_cfg, dict):
            return

        if continuity_cfg.get("enable_topic_similarity_matching") is True:
            self.warnings.append(topic_similarity_enabled_warning())

    def _validate_end_of_session_config(self) -> None:
        """Validate end-of-session configuration."""
        eos_config = self.config_data.get("end_of_session", {})

        if not eos_config:
            # No end_of_session config provided - defaults will be used
            return

        enabled = eos_config.get("enabled", False)
        emit_events = eos_config.get("emit_events", True)

        # Validate detect-only mode (enabled=True, emit_events=False)
        if enabled and not emit_events:
            self.warnings.append(
                "end_of_session.enabled=True but end_of_session.emit_events=False. "
                "This enables detect-only mode: detection runs but no events are emitted."
            )

        # Field-level validation (emission_ttl_seconds >= 0, dispatch_timeout_seconds >= 0.0)
        # is handled by Pydantic Field constraints when the config is loaded.
        # This semantic validation focuses on business logic consistency.

    def _get_recovery_instructions(self) -> list[str]:
        """Generate actionable recovery instructions based on errors."""
        instructions: list[str] = []

        for error in self.errors:
            if "wire_capture" in error and "log_file" in error:
                instructions.append(
                    "Fix wire capture configuration:\n"
                    "  1. Change 'logging.log_file' to 'logging.capture_file'\n"
                    "  2. Set 'logging.log_file' to null or a different path for general logs\n"
                    "  3. Example:\n"
                    "     logging:\n"
                    "       log_file: null  # or 'logs/app.log'\n"
                    "       capture_file: 'logs/wire_capture.log'"
                )
            elif "same file" in error:
                instructions.append(
                    "Use separate files for different log types:\n"
                    "  - logging.log_file: for general application logs\n"
                    "  - logging.capture_file: for wire-level HTTP capture\n"
                    "  These must be different files or one should be null."
                )
            elif "level" in error and "invalid" in error:
                instructions.append(
                    "Fix log level:\n"
                    "  Set logging.level to one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
                )

        if not instructions:
            instructions.append(
                "Check the configuration file syntax and ensure all required fields are present."
            )

        return instructions


def validate_config_semantics(
    config_data: dict[str, Any], config_path: str | Path
) -> None:
    """Validate configuration for semantic correctness.

    Args:
        config_data: The loaded configuration data
        config_path: Path to the configuration file (for error reporting)

    Raises:
        ConfigurationError: If validation fails
    """
    validator = ConfigurationValidator(config_data, config_path)
    validator.validate()


def validate_static_route(config: AppConfig) -> None:
    """Validate that static_route backend exists in registered backends.

    This function validates the runtime AppConfig object (post YAML/ENV/CLI merge)
    and assumes connector auto-discovery has already happened.

    Args:
        config: The final resolved AppConfig instance

    Raises:
        ConfigurationError: If static_route specifies an invalid backend name or
            has an invalid format

    Note:
        This validation runs against the runtime AppConfig object, not raw YAML dict data.
        Connector auto-discovery (importing src.connectors) must have occurred before
        calling this function.
    """
    static_route = config.backends.static_route

    # No-op if static_route is None or empty string
    if not static_route:
        return

    # Parse <backend_name>:<model_name> format
    parts = static_route.split(":", 1)

    # Validate format: must contain ':' separator and model part must not be empty
    if len(parts) != 2:
        error_msg = (
            f"Invalid static_route format: '{static_route}'. "
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini-oauth-plan:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini-oauth-plan:gemini-2.5-pro",
            },
        )

    backend_name, model_name = parts

    # Validate model part is not empty
    if not model_name or not model_name.strip():
        error_msg = (
            f"Invalid static_route format: '{static_route}'. "
            f"Model name cannot be empty.\n"
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini-oauth-plan:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini-oauth-plan:gemini-2.5-pro",
            },
        )

    # Validate backend exists in registered backends
    registered_backends = backend_registry.get_registered_backends()

    if backend_name not in registered_backends:
        available_backends = sorted(registered_backends)
        available_backends_str = ", ".join(available_backends)

        error_msg = (
            f"Invalid backend '{backend_name}' specified in static_route.\n"
            f"Backend '{backend_name}' is not registered.\n"
            f"Available backends: {available_backends_str}\n"
            f"Current static_route value: '{static_route}'\n"
            f"Expected format: <backend_name>:<model_name>\n"
            f"Example: gemini-oauth-plan:gemini-2.5-pro"
        )
        logger.error("Static route validation failed: %s", error_msg)
        raise ConfigurationError(
            message=error_msg,
            details={
                "invalid_backend": backend_name,
                "available_backends": available_backends,
                "static_route": static_route,
                "expected_format": "<backend_name>:<model_name>",
                "example": "gemini-oauth-plan:gemini-2.5-pro",
            },
        )
