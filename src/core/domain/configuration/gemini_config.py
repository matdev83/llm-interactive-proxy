"""
Gemini-specific configuration.

This module provides configuration structures for Gemini-specific features.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration import IBackendSpecificConfig

logger = logging.getLogger(__name__)


class GeminiGenerationConfig(ValueObject, IBackendSpecificConfig):
    """Configuration for Gemini generation parameters.

    This class handles Gemini-specific generation parameters like thinking budget
    and other generation settings.
    """

    model_config = ConfigDict(
        # Ignore extra attributes to suppress warnings about field names shadowing parent attributes
        extra="ignore",
        # Other config options can be added here as needed
    )

    # Thinking configuration
    thinking_config: dict[str, Any] = Field(default_factory=dict)

    # Safety settings
    safety_settings: dict[str, Any] = Field(default_factory=dict)

    # Generation configuration
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_output_tokens: int | None = None
    candidate_count: int | None = None
    stop_sequences: list[str] | None = None

    @classmethod
    @field_validator("temperature")
    def validate_temperature(cls, v: float | None) -> float | None:
        """Validate that temperature is within the allowed range."""
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return v

    @classmethod
    @field_validator("top_p")
    def validate_top_p(cls, v: float | None) -> float | None:
        """Validate that top_p is within the allowed range."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError("Top_p must be between 0.0 and 1.0")
        return v

    @classmethod
    @field_validator("top_k")
    def validate_top_k(cls, v: int | None) -> int | None:
        """Validate that top_k is positive."""
        if v is not None and v <= 0:
            raise ValueError("Top_k must be positive")
        return v

    @classmethod
    @field_validator("max_output_tokens")
    def validate_max_output_tokens(cls, v: int | None) -> int | None:
        """Validate that max_output_tokens is positive."""
        if v is not None and v <= 0:
            raise ValueError("Max output tokens must be positive")
        return v

    def with_thinking_budget(self, budget: int) -> GeminiGenerationConfig:
        """Create a new config with updated thinking budget."""
        thinking_config = dict(self.thinking_config)
        thinking_config["thinkingBudget"] = budget
        return self.model_copy(update={"thinking_config": thinking_config})

    def with_temperature(self, temperature: float) -> GeminiGenerationConfig:
        """Create a new config with updated temperature."""
        return self.model_copy(update={"temperature": temperature})

    def with_generation_config(
        self, config_json: str | dict[str, Any]
    ) -> GeminiGenerationConfig:
        """Create a new config with updated generation parameters from JSON.

        Args:
            config_json: JSON string or dictionary with generation parameters

        Returns:
            Updated configuration
        """
        if isinstance(config_json, str):
            try:
                config_dict = json.loads(config_json)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON for generation config")
        else:
            config_dict = config_json

        # Extract known parameters
        updates = {}

        # Handle thinking config
        if "thinkingConfig" in config_dict and isinstance(
            config_dict["thinkingConfig"], dict
        ):
            updates["thinking_config"] = config_dict["thinkingConfig"]

        # Handle safety settings
        if "safetySettings" in config_dict and isinstance(
            config_dict["safetySettings"], dict
        ):
            updates["safety_settings"] = config_dict["safetySettings"]

        # Handle generation parameters
        for param in [
            "temperature",
            "top_p",
            "top_k",
            "max_output_tokens",
            "candidate_count",
            "stop_sequences",
        ]:
            if param in config_dict:
                updates[param] = config_dict[param]

        return self.model_copy(update=updates)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary for the API.

        Returns:
            Dictionary representation of the configuration
        """
        result: dict[str, Any] = {}

        # Add thinking config if present
        if self.thinking_config:
            result["thinkingConfig"] = self.thinking_config

        # Add safety settings if present
        if self.safety_settings:
            result["safetySettings"] = self.safety_settings

        # Add generation parameters if present
        for param, value in {
            "temperature": self.temperature,
            "topP": self.top_p,
            "topK": self.top_k,
            "maxOutputTokens": self.max_output_tokens,
            "candidateCount": self.candidate_count,
            "stopSequences": self.stop_sequences,
        }.items():
            if value is not None:
                result[param] = value

        return result
