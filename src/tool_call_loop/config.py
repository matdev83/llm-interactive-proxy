"""Configuration for tool call loop detection.

This module provides configuration structures and validation for tool call loop detection.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolLoopMode(str, Enum):
    """Mode of operation for tool call loop detection."""

    BREAK = "break"
    CHANCE_THEN_BREAK = "chance_then_break"


@dataclass
class ToolCallLoopConfig:
    """Configuration for tool call loop detection."""

    # Whether tool call loop detection is enabled
    enabled: bool = True

    # Maximum number of consecutive identical tool calls before action is taken
    max_repeats: int = 4

    # Time window in seconds for considering tool calls part of a pattern
    ttl_seconds: int = 120

    # How to handle detected tool call loops
    mode: ToolLoopMode = ToolLoopMode.BREAK

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if self.max_repeats < 2:
            errors.append("max_repeats must be at least 2")

        if self.ttl_seconds < 1:
            errors.append("ttl_seconds must be positive")

        return errors

    @classmethod
    def from_env_vars(cls, env_vars: dict[str, str]) -> ToolCallLoopConfig:
        """Create a configuration from environment variables.

        Args:
            env_vars: Dictionary of environment variables

        Returns:
            A ToolCallLoopConfig instance
        """
        config = cls()

        if "TOOL_LOOP_DETECTION_ENABLED" in env_vars:
            value = env_vars["TOOL_LOOP_DETECTION_ENABLED"].lower()
            config.enabled = value in ("true", "1", "yes")

        if "TOOL_LOOP_MAX_REPEATS" in env_vars:
            with contextlib.suppress(ValueError):
                config.max_repeats = int(env_vars["TOOL_LOOP_MAX_REPEATS"])

        if "TOOL_LOOP_TTL_SECONDS" in env_vars:
            with contextlib.suppress(ValueError):
                config.ttl_seconds = int(env_vars["TOOL_LOOP_TTL_SECONDS"])

        if "TOOL_LOOP_MODE" in env_vars:
            mode_str = env_vars["TOOL_LOOP_MODE"].lower()
            if mode_str == "chance":  # Allow shorthand
                mode_str = "chance_then_break"

            with contextlib.suppress(ValueError):
                config.mode = ToolLoopMode(mode_str)

        return config

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> ToolCallLoopConfig:
        """Create a configuration from a dictionary.

        Args:
            config_dict: Dictionary with configuration values

        Returns:
            A ToolCallLoopConfig instance
        """
        config = cls()

        if "enabled" in config_dict:
            config.enabled = bool(config_dict["enabled"])

        if "max_repeats" in config_dict:
            with contextlib.suppress(ValueError):
                config.max_repeats = int(config_dict["max_repeats"])

        if "ttl_seconds" in config_dict:
            with contextlib.suppress(ValueError):
                config.ttl_seconds = int(config_dict["ttl_seconds"])

        # Convert mode string to enum if needed
        if "mode" in config_dict:
            if isinstance(config_dict["mode"], str):
                mode_str = config_dict["mode"].lower()
                if mode_str == "chance":  # Allow shorthand
                    mode_str = "chance_then_break"

                with contextlib.suppress(ValueError):
                    config.mode = ToolLoopMode(mode_str)
            elif isinstance(config_dict["mode"], ToolLoopMode):
                config.mode = config_dict["mode"]

        return config

    def to_dict(self) -> dict[str, bool | int | str]:
        """Convert configuration to a dictionary.

        Returns:
            Dictionary representation of the configuration
        """
        return {
            "enabled": self.enabled,
            "max_repeats": self.max_repeats,
            "ttl_seconds": self.ttl_seconds,
            "mode": self.mode.value,
        }

    def merge_with(self, override: ToolCallLoopConfig | None) -> ToolCallLoopConfig:
        """Create a new config by merging with an override config.

        Args:
            override: Configuration that takes precedence

        Returns:
            A new ToolCallLoopConfig instance with merged values
        """
        if override is None:
            return self

        result = ToolCallLoopConfig()
        result.enabled = override.enabled
        result.max_repeats = override.max_repeats
        result.ttl_seconds = override.ttl_seconds
        result.mode = override.mode

        return result
