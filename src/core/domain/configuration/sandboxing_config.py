"""Configuration for file access sandboxing feature."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from src.core.interfaces.model_bases import DomainModel


class SandboxingConfiguration(DomainModel):
    """Immutable configuration for file access sandboxing.

    This configuration controls the file access sandboxing feature that prevents
    LLM agents from performing file-changing operations outside of the detected
    project root directory.
    """

    enabled: bool = False
    """Whether file access sandboxing is enabled."""

    strict_mode: bool = False
    """Whether to block tool calls with unparseable paths (default: false)."""

    allow_parent_access: bool = False
    """Whether to allow access to parent directories of the project root (default: false)."""

    custom_tool_patterns: list[str] = Field(default_factory=list)
    """Additional regex patterns for file-changing tools."""

    excluded_tools: list[str] = Field(default_factory=list)
    """Regex patterns for tools to exempt from sandboxing."""

    # Default file-changing tool patterns based on TOOL_INVENTORY.md
    default_tool_patterns: list[str] = Field(
        default_factory=lambda: [
            # File editors/creators
            r"write_to_file",
            r"write_file",
            r"fsWrite",
            r"replace_in_file",
            r"str_replace",
            r"strReplace",
            r"edit_file",
            r"patch_file",
            r"apply_diff",
            r"apply_patch",
            r"delete_file",
            r"deleteFile",
            r"remove_file",
            r"create_file",
            r"move_file",
            r"rename_file",
            r"copy_file",
            r"insert_content",
            r"search_and_replace",
            r"generate_image",
            # Shell/command runners
            r"Execute",
            r"execute_command",
            r"run_shell_command",
            r"run_terminal_command",
            r"exec_command",
            r"bash",
            r"shell",
            r"local_shell",
            r"container\.exec",
        ]
    )
    """Default regex patterns for identifying file-changing tools."""

    # Common file path parameter names based on TOOL_INVENTORY.md
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

    @field_validator("custom_tool_patterns")
    @classmethod
    def validate_custom_tool_patterns(cls, v: list[str]) -> list[str]:
        """Validate that custom tool patterns are valid regex patterns."""
        if not v:
            return v

        invalid_patterns = []
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                invalid_patterns.append(f"'{pattern}': {e}")

        if invalid_patterns:
            raise ValueError(
                f"Invalid regex patterns in custom_tool_patterns: {', '.join(invalid_patterns)}"
            )

        return v

    @field_validator("excluded_tools")
    @classmethod
    def validate_excluded_tools(cls, v: list[str]) -> list[str]:
        """Validate that excluded tool patterns are valid regex patterns."""
        if not v:
            return v

        invalid_patterns = []
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                invalid_patterns.append(f"'{pattern}': {e}")

        if invalid_patterns:
            raise ValueError(
                f"Invalid regex patterns in excluded_tools: {', '.join(invalid_patterns)}"
            )

        return v

    @field_validator("path_parameter_names")
    @classmethod
    def validate_path_parameter_names(cls, v: list[str]) -> list[str]:
        """Validate that path parameter names are non-empty strings."""
        if not v:
            raise ValueError("path_parameter_names cannot be empty")

        invalid_names = [name for name in v if not name or not isinstance(name, str)]
        if invalid_names:
            raise ValueError(
                f"path_parameter_names must contain non-empty strings, found invalid entries: {invalid_names}"
            )

        return v

    def validate_configuration(self) -> list[str]:
        """Validate the entire configuration and return a list of error messages.

        Returns:
            List of error messages. Empty list if configuration is valid.
        """
        errors = []

        # Validate that default tool patterns are valid regex
        for pattern in self.default_tool_patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                errors.append(f"Invalid default tool pattern '{pattern}': {e}")

        # Check for conflicting settings
        if self.strict_mode and not self.enabled:
            errors.append(
                "strict_mode is enabled but sandboxing is disabled. "
                "strict_mode has no effect when sandboxing is disabled."
            )

        if self.allow_parent_access and not self.enabled:
            errors.append(
                "allow_parent_access is enabled but sandboxing is disabled. "
                "allow_parent_access has no effect when sandboxing is disabled."
            )

        # Validate that we have at least some tool patterns
        if (
            self.enabled
            and not self.default_tool_patterns
            and not self.custom_tool_patterns
        ):
            errors.append(
                "Sandboxing is enabled but no tool patterns are defined. "
                "At least one tool pattern is required for sandboxing to function."
            )

        # Validate that we have path parameter names
        if self.enabled and not self.path_parameter_names:
            errors.append(
                "Sandboxing is enabled but no path parameter names are defined. "
                "At least one path parameter name is required for sandboxing to function."
            )

        return errors
