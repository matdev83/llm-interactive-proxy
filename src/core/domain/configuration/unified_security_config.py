"""
Unified Security Framework Configuration.

This module provides a unified configuration for all tool call security features
including dangerous command detection and file sandboxing.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from src.core.domain.tool_constants import FileEditingTools, ShellExecutionTools
from src.core.interfaces.model_bases import DomainModel


class DangerousCommandRuleConfig(DomainModel):
    """Configuration for a single dangerous command detection rule."""

    name: str
    """Unique identifier for this rule."""

    pattern: str
    """Regex pattern to match dangerous commands."""

    description: str = ""
    """Human-readable description of what this rule catches."""

    enabled: bool = True
    """Whether this rule is active."""

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate that the pattern is a valid regex."""
        try:
            re.compile(v, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e
        return v


class DangerousCommandsConfig(DomainModel):
    """Configuration for dangerous command detection feature."""

    enabled: bool = True
    """Whether dangerous command detection is enabled."""

    # Default tool names that run shell commands
    tool_names: list[str] = Field(default_factory=lambda: ShellExecutionTools.get_all())
    """Tool names to monitor for dangerous commands."""

    rules: list[DangerousCommandRuleConfig] = Field(default_factory=list)
    """Custom dangerous command rules (in addition to built-in rules)."""

    max_command_length: int = 10000
    """Maximum command length to analyze (for performance)."""

    # Built-in rules are loaded separately to keep config clean
    use_builtin_rules: bool = True
    """Whether to use built-in dangerous command rules."""


class FileSandboxingConfig(DomainModel):
    """Configuration for file access sandboxing feature."""

    enabled: bool = False
    """Whether file access sandboxing is enabled."""

    strict_mode: bool = False
    """Whether to block tool calls with unparseable paths (default: false)."""

    allow_parent_access: bool = False
    """Whether to allow access to parent directories of the project root."""

    custom_tool_patterns: list[str] = Field(default_factory=list)
    """Additional regex patterns for file-changing tools."""

    excluded_tools: list[str] = Field(default_factory=list)
    """Regex patterns for tools to exempt from sandboxing."""

    # Default file-changing tool patterns (use iterable unpacking to avoid RUF005)
    default_tool_patterns: list[str] = Field(
        default_factory=lambda: [*FileEditingTools.get_all_patterns(), ShellExecutionTools.PATTERN]
    )
    """Default regex patterns for identifying file-changing tools."""

    path_parameter_names: list[str] = Field(
        default_factory=lambda: [
            "path",
            "file_path",
            "filepath",
            "file",
            "target",
            "target_file",
            "destination",
            "dest",
            "source",
            "src",
            "fileName",
            "filePath",
            "image",
            "patch",
            "diff",
            "paths",
            "files",
            "file_list",
            "targets",
            "cwd",
            "workdir",
            "directory",
            "dir",
        ]
    )
    """Parameter names that may contain file paths in tool call arguments."""

    @field_validator("custom_tool_patterns", "excluded_tools")
    @classmethod
    def validate_patterns(cls, v: list[str]) -> list[str]:
        """Validate that patterns are valid regex."""
        if not v:
            return v
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return v


class LoopPreventionConfig(DomainModel):
    """Configuration for security check loop prevention."""

    max_retries: int = 3
    """Maximum number of retry attempts before returning terminal error."""

    use_escalating_messages: bool = True
    """Whether to use progressively stronger warning messages."""

    # Custom escalating messages (optional - uses defaults if empty)
    custom_messages: list[str] = Field(default_factory=list)
    """Custom escalating warning messages (1 per retry level)."""


class UnifiedSecurityConfig(DomainModel):
    """Unified configuration for all tool call security features.

    This configuration combines dangerous command detection and file sandboxing
    into a single, cohesive security framework with shared settings.
    """

    enabled: bool = True
    """Master switch for all security features."""

    priority: int = 100
    """Handler priority (higher runs first)."""

    dangerous_commands: DangerousCommandsConfig = Field(
        default_factory=DangerousCommandsConfig
    )
    """Configuration for dangerous command detection."""

    file_sandboxing: FileSandboxingConfig = Field(default_factory=FileSandboxingConfig)
    """Configuration for file access sandboxing."""

    loop_prevention: LoopPreventionConfig = Field(default_factory=LoopPreventionConfig)
    """Configuration for retry loop prevention."""

    # Shared shell tool patterns (used by both features)
    shell_tool_patterns: list[str] = Field(
        default_factory=lambda: [ShellExecutionTools.PATTERN]
    )
    """Shared patterns for identifying shell/command execution tools."""

    def is_any_feature_enabled(self) -> bool:
        """Check if any security feature is active."""
        return self.enabled and (
            self.dangerous_commands.enabled or self.file_sandboxing.enabled
        )

    @classmethod
    def from_legacy_configs(
        cls,
        dangerous_command_config: Any | None = None,
        sandboxing_config: Any | None = None,
    ) -> UnifiedSecurityConfig:
        """Create unified config from legacy separate configs.

        This provides backward compatibility during migration.
        """
        config = cls()

        if dangerous_command_config is not None:
            # Map legacy DangerousCommandConfig fields
            if hasattr(dangerous_command_config, "tool_names"):
                config.dangerous_commands.tool_names = list(
                    dangerous_command_config.tool_names
                )
            if hasattr(dangerous_command_config, "max_command_length"):
                config.dangerous_commands.max_command_length = (
                    dangerous_command_config.max_command_length
                )
            if hasattr(dangerous_command_config, "rules"):
                config.dangerous_commands.rules = [
                    DangerousCommandRuleConfig(
                        name=r.name,
                        pattern=r.pattern,
                        description=getattr(r, "description", ""),
                    )
                    for r in dangerous_command_config.rules
                ]

        if sandboxing_config is not None:
            # Map legacy SandboxingConfiguration fields
            if hasattr(sandboxing_config, "enabled"):
                config.file_sandboxing.enabled = sandboxing_config.enabled
            if hasattr(sandboxing_config, "strict_mode"):
                config.file_sandboxing.strict_mode = sandboxing_config.strict_mode
            if hasattr(sandboxing_config, "allow_parent_access"):
                config.file_sandboxing.allow_parent_access = (
                    sandboxing_config.allow_parent_access
                )
            if hasattr(sandboxing_config, "custom_tool_patterns"):
                config.file_sandboxing.custom_tool_patterns = list(
                    sandboxing_config.custom_tool_patterns
                )
            if hasattr(sandboxing_config, "excluded_tools"):
                config.file_sandboxing.excluded_tools = list(
                    sandboxing_config.excluded_tools
                )
            if hasattr(sandboxing_config, "path_parameter_names"):
                config.file_sandboxing.path_parameter_names = list(
                    sandboxing_config.path_parameter_names
                )

        return config
