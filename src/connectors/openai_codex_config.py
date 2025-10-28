"""Configuration validation for OpenAI Codex backend compatibility layer.

This module provides validation logic for the Codex-KiloCode compatibility layer
configuration, ensuring all settings are valid and within acceptable ranges.
"""

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass
class DetectionConfig:
    """Configuration for KiloCode client detection."""

    cache_ttl_seconds: int = 3600
    heuristic_threshold: int = 2
    metadata_enabled: bool = True
    header_enabled: bool = True
    heuristic_enabled: bool = True

    def validate(self) -> list[str]:
        """Validate detection configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.cache_ttl_seconds < 0:
            errors.append("detection.cache_ttl_seconds must be non-negative")
        if self.cache_ttl_seconds > 86400:
            errors.append(
                "detection.cache_ttl_seconds should not exceed 86400 (24 hours)"
            )

        if self.heuristic_threshold < 1:
            errors.append("detection.heuristic_threshold must be at least 1")
        if self.heuristic_threshold > 10:
            errors.append(
                "detection.heuristic_threshold should not exceed 10 "
                "(may cause false positives)"
            )

        if not any(
            [self.metadata_enabled, self.header_enabled, self.heuristic_enabled]
        ):
            errors.append(
                "At least one detection method must be enabled "
                "(metadata, header, or heuristic)"
            )

        return errors


@dataclass
class CommandExecutionConfig:
    """Configuration for command execution security."""

    allowed_shells: list[str]
    restrict_to_workspace: bool = True
    max_output_size: int = 1048576  # 1 MB

    def validate(self) -> list[str]:
        """Validate command execution configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.allowed_shells:
            errors.append(
                "translation.command_execution.allowed_shells cannot be empty"
            )

        valid_shells = {"bash", "sh", "zsh", "cmd", "powershell", "pwsh"}
        for shell in self.allowed_shells:
            if shell not in valid_shells:
                errors.append(
                    f"Invalid shell '{shell}' in allowed_shells. "
                    f"Valid options: {', '.join(sorted(valid_shells))}"
                )

        if self.max_output_size < 1024:
            errors.append(
                "translation.command_execution.max_output_size must be at least 1024 bytes"
            )
        if self.max_output_size > 104857600:  # 100 MB
            errors.append(
                "translation.command_execution.max_output_size should not exceed "
                "104857600 (100 MB)"
            )

        return errors


@dataclass
class FileOperationsConfig:
    """Configuration for file operation security."""

    restrict_to_workspace: bool = True
    max_file_size: int = 10485760  # 10 MB
    allowed_extensions: list[str] | None = None
    blocked_patterns: list[str] | None = None

    def validate(self) -> list[str]:
        """Validate file operations configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.max_file_size < 1024:
            errors.append(
                "translation.file_operations.max_file_size must be at least 1024 bytes"
            )
        if self.max_file_size > 1073741824:  # 1 GB
            errors.append(
                "translation.file_operations.max_file_size should not exceed "
                "1073741824 (1 GB)"
            )

        if self.allowed_extensions is not None:
            for ext in self.allowed_extensions:
                if not ext.startswith("."):
                    errors.append(
                        f"File extension '{ext}' must start with a dot (e.g., '.py')"
                    )

        return errors


@dataclass
class TranslationConfig:
    """Configuration for tool translation."""

    max_tool_execution_timeout: int = 30
    result_format: str = "kilo_standard"
    tools_enabled: dict[str, bool] | None = None
    command_execution: CommandExecutionConfig | None = None
    file_operations: FileOperationsConfig | None = None

    def validate(self) -> list[str]:
        """Validate translation configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.max_tool_execution_timeout < 1:
            errors.append("translation.max_tool_execution_timeout must be at least 1")
        if self.max_tool_execution_timeout > 300:
            errors.append(
                "translation.max_tool_execution_timeout should not exceed 300 (5 minutes)"
            )

        valid_formats = {"kilo_standard", "verbose"}
        if self.result_format not in valid_formats:
            errors.append(
                f"translation.result_format must be one of: {', '.join(valid_formats)}"
            )

        if self.tools_enabled is not None:
            valid_tools = {
                "read_file",
                "list_files",
                "execute_command",
                "codebase_search",
                "search_files",
                "use_mcp_tool",
                "access_mcp_resource",
                "attempt_completion",
                "ask_followup_question",
                "search_and_replace",
                "write_to_file",
                "insert_content",
                "edit_file",
            }
            for tool in self.tools_enabled:
                if tool not in valid_tools:
                    errors.append(
                        f"Unknown tool '{tool}' in translation.tools. "
                        f"Valid tools: {', '.join(sorted(valid_tools))}"
                    )

        if self.command_execution is not None:
            errors.extend(self.command_execution.validate())

        if self.file_operations is not None:
            errors.extend(self.file_operations.validate())

        return errors


@dataclass
class TelemetryConfig:
    """Configuration for telemetry and monitoring."""

    log_translations: bool = True
    log_detection: bool = True
    emit_metrics: bool = True
    log_level: str = "INFO"
    include_xml_in_errors: bool = False

    def validate(self) -> list[str]:
        """Validate telemetry configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level not in valid_log_levels:
            errors.append(
                f"telemetry.log_level must be one of: {', '.join(valid_log_levels)}"
            )

        return errors


@dataclass
class ErrorHandlingConfig:
    """Configuration for error handling."""

    detailed_errors: bool = True
    include_suggestions: bool = True
    fail_fast: bool = True

    def validate(self) -> list[str]:
        """Validate error handling configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        # No validation needed for boolean flags
        return []


@dataclass
class CompatibilityLayerConfig:
    """Complete configuration for Codex-KiloCode compatibility layer."""

    enabled: bool = False
    detection: DetectionConfig | None = None
    translation: TranslationConfig | None = None
    telemetry: TelemetryConfig | None = None
    error_handling: ErrorHandlingConfig | None = None

    def validate(self) -> list[str]:
        """Validate complete compatibility layer configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if self.detection is not None:
            errors.extend(self.detection.validate())

        if self.translation is not None:
            errors.extend(self.translation.validate())

        if self.telemetry is not None:
            errors.extend(self.telemetry.validate())

        if self.error_handling is not None:
            errors.extend(self.error_handling.validate())

        return errors

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "CompatibilityLayerConfig":
        """Create configuration from dictionary.

        Args:
            config_dict: Configuration dictionary from YAML

        Returns:
            CompatibilityLayerConfig instance
        """
        enabled = config_dict.get("enabled", False)

        # Parse detection config
        detection = None
        if "detection" in config_dict:
            det_dict = config_dict["detection"]
            methods = det_dict.get("methods", {})
            detection = DetectionConfig(
                cache_ttl_seconds=det_dict.get("cache_ttl_seconds", 3600),
                heuristic_threshold=det_dict.get("heuristic_threshold", 2),
                metadata_enabled=methods.get("metadata", True),
                header_enabled=methods.get("header", True),
                heuristic_enabled=methods.get("heuristic", True),
            )

        # Parse translation config
        translation = None
        if "translation" in config_dict:
            trans_dict = config_dict["translation"]

            # Parse command execution config
            cmd_exec = None
            if "command_execution" in trans_dict:
                cmd_dict = trans_dict["command_execution"]
                cmd_exec = CommandExecutionConfig(
                    allowed_shells=cmd_dict.get(
                        "allowed_shells", ["bash", "sh", "cmd", "powershell"]
                    ),
                    restrict_to_workspace=cmd_dict.get("restrict_to_workspace", True),
                    max_output_size=cmd_dict.get("max_output_size", 1048576),
                )

            # Parse file operations config
            file_ops = None
            if "file_operations" in trans_dict:
                file_dict = trans_dict["file_operations"]
                file_ops = FileOperationsConfig(
                    restrict_to_workspace=file_dict.get("restrict_to_workspace", True),
                    max_file_size=file_dict.get("max_file_size", 10485760),
                    allowed_extensions=file_dict.get("allowed_extensions"),
                    blocked_patterns=file_dict.get("blocked_patterns"),
                )

            translation = TranslationConfig(
                max_tool_execution_timeout=trans_dict.get(
                    "max_tool_execution_timeout", 30
                ),
                result_format=trans_dict.get("result_format", "kilo_standard"),
                tools_enabled=trans_dict.get("tools"),
                command_execution=cmd_exec,
                file_operations=file_ops,
            )

        # Parse telemetry config
        telemetry = None
        if "telemetry" in config_dict:
            telem_dict = config_dict["telemetry"]
            telemetry = TelemetryConfig(
                log_translations=telem_dict.get("log_translations", True),
                log_detection=telem_dict.get("log_detection", True),
                emit_metrics=telem_dict.get("emit_metrics", True),
                log_level=telem_dict.get("log_level", "INFO"),
                include_xml_in_errors=telem_dict.get("include_xml_in_errors", False),
            )

        # Parse error handling config
        error_handling = None
        if "error_handling" in config_dict:
            err_dict = config_dict["error_handling"]
            error_handling = ErrorHandlingConfig(
                detailed_errors=err_dict.get("detailed_errors", True),
                include_suggestions=err_dict.get("include_suggestions", True),
                fail_fast=err_dict.get("fail_fast", True),
            )

        return cls(
            enabled=enabled,
            detection=detection,
            translation=translation,
            telemetry=telemetry,
            error_handling=error_handling,
        )


def load_and_validate_config(
    config_path: str,
) -> tuple[CompatibilityLayerConfig, list[str]]:
    """Load and validate compatibility layer configuration from YAML file.

    Args:
        config_path: Path to backend configuration YAML file

    Returns:
        Tuple of (config, validation_errors)
        If validation_errors is non-empty, the configuration is invalid
    """
    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
    except FileNotFoundError:
        return (
            CompatibilityLayerConfig(),
            [f"Configuration file not found: {config_path}"],
        )
    except yaml.YAMLError as e:
        return (
            CompatibilityLayerConfig(),
            [f"Invalid YAML syntax: {e}"],
        )

    if not isinstance(config_data, dict):
        return (
            CompatibilityLayerConfig(),
            ["Configuration file must contain a YAML dictionary"],
        )

    compat_layer_dict = config_data.get("compatibility_layer", {})
    config = CompatibilityLayerConfig.from_dict(compat_layer_dict)
    validation_errors = config.validate()

    return config, validation_errors


def validate_config_dict(config_dict: dict[str, Any]) -> list[str]:
    """Validate compatibility layer configuration from dictionary.

    Args:
        config_dict: Configuration dictionary (compatibility_layer section)

    Returns:
        List of validation error messages (empty if valid)
    """
    config = CompatibilityLayerConfig.from_dict(config_dict)
    return config.validate()
