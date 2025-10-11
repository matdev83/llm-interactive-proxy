"""
Pydantic models for backend configuration management.

This module defines the data structures for backend-specific configurations,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


class GeminiGenerationConfig(BaseModel):
    """Gemini generation configuration."""

    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Generation temperature"
    )
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling parameter"
    )
    top_k: int | None = Field(
        default=None, ge=1, description="Top-k sampling parameter"
    )
    candidate_count: int | None = Field(
        default=None, ge=1, description="Number of candidates to generate"
    )
    max_output_tokens: int | None = Field(
        default=None, ge=1, description="Maximum output tokens"
    )
    stop_sequences: list | None = Field(default=None, description="Stop sequences")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for backward compatibility."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeminiGenerationConfig":
        """Create from dictionary for backward compatibility."""
        return cls.model_validate(data)


class GeminiBackendConfig(BaseModel):
    """Gemini-specific backend configuration."""

    thinking_budget: int | None = Field(
        default=None, ge=0, description="Thinking budget for reasoning"
    )
    generation_config: GeminiGenerationConfig | None = Field(
        default=None, description="Generation configuration"
    )
    gemini_generation_config: GeminiGenerationConfig | None = Field(
        default=None, description="Legacy generation config field"
    )
    safety_settings: list | None = Field(default=None, description="Safety settings")
    tools: list | None = Field(default=None, description="Available tools")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for API calls."""
        result = self.model_dump(exclude_none=True)

        # Handle nested generation config
        if self.generation_config:
            result["generation_config"] = self.generation_config.to_dict()
        if self.gemini_generation_config:
            result["gemini_generation_config"] = self.gemini_generation_config.to_dict()

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeminiBackendConfig":
        """Create from dictionary for backward compatibility."""
        # Handle nested generation config
        if "generation_config" in data and isinstance(data["generation_config"], dict):
            data["generation_config"] = GeminiGenerationConfig.from_dict(
                data["generation_config"]
            )
        if "gemini_generation_config" in data and isinstance(
            data["gemini_generation_config"], dict
        ):
            data["gemini_generation_config"] = GeminiGenerationConfig.from_dict(
                data["gemini_generation_config"]
            )

        return cls.model_validate(data)


class OpenAIBackendConfig(BaseModel):
    """OpenAI-specific backend configuration."""

    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Generation temperature"
    )
    max_tokens: int | None = Field(default=None, ge=1, description="Maximum tokens")
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling parameter"
    )
    frequency_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Frequency penalty"
    )
    presence_penalty: float | None = Field(
        default=None, ge=-2.0, le=2.0, description="Presence penalty"
    )
    stop: str | list | None = Field(default=None, description="Stop sequences")
    logit_bias: dict[str, float] | None = Field(default=None, description="Logit bias")
    user: str | None = Field(default=None, description="User identifier")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for API calls."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenAIBackendConfig":
        """Create from dictionary for backward compatibility."""
        return cls.model_validate(data)


class AnthropicBackendConfig(BaseModel):
    """Anthropic-specific backend configuration."""

    temperature: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Generation temperature"
    )
    max_tokens: int | None = Field(default=None, ge=1, description="Maximum tokens")
    top_p: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Top-p sampling parameter"
    )
    top_k: int | None = Field(
        default=None, ge=1, description="Top-k sampling parameter"
    )
    stop_sequences: list | None = Field(default=None, description="Stop sequences")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for API calls."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnthropicBackendConfig":
        """Create from dictionary for backward compatibility."""
        return cls.model_validate(data)


class BackendConfiguration(BaseModel):
    """Complete backend configuration for any backend type."""

    backend_type: str = Field(description="Backend type (gemini, openai, anthropic)")
    extra_body: dict[str, Any] = Field(
        default_factory=dict, description="Additional configuration parameters"
    )
    gemini_config: GeminiBackendConfig | None = Field(
        default=None, description="Gemini-specific configuration"
    )
    openai_config: OpenAIBackendConfig | None = Field(
        default=None, description="OpenAI-specific configuration"
    )
    anthropic_config: AnthropicBackendConfig | None = Field(
        default=None, description="Anthropic-specific configuration"
    )

    def get_backend_config(
        self,
    ) -> GeminiBackendConfig | OpenAIBackendConfig | AnthropicBackendConfig | None:
        """Get the backend-specific configuration."""
        if self.backend_type == "gemini":
            return self.gemini_config
        elif self.backend_type == "openai":
            return self.openai_config
        elif self.backend_type == "anthropic":
            return self.anthropic_config
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for API calls."""
        result: dict[str, Any] = {
            "backend_type": self.backend_type,
            "extra_body": dict(self.extra_body),
        }

        # Add backend-specific config to extra_body
        backend_config = self.get_backend_config()
        if backend_config:
            extra_body_value = result["extra_body"]
            if isinstance(extra_body_value, dict):
                extra_body_value.update(backend_config.to_dict())

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackendConfiguration":
        """Create from dictionary for backward compatibility."""
        backend_type = data.get("backend_type", "openai")
        extra_body = data.get("extra_body", {})

        # Extract backend-specific config from extra_body
        config_data = {"backend_type": backend_type, "extra_body": dict(extra_body)}

        if backend_type == "gemini":
            config_data["gemini_config"] = GeminiBackendConfig.from_dict(extra_body)
        elif backend_type == "openai":
            config_data["openai_config"] = OpenAIBackendConfig.from_dict(extra_body)
        elif backend_type == "anthropic":
            config_data["anthropic_config"] = AnthropicBackendConfig.from_dict(
                extra_body
            )

        return cls.model_validate(config_data)


# Factory functions for creating backend configurations
def create_gemini_backend_config(
    thinking_budget: int | None = None,
    generation_config: dict[str, Any] | None = None,
    **kwargs,
) -> GeminiBackendConfig:
    """Create Gemini backend configuration with validation."""
    config_data = {"thinking_budget": thinking_budget, **kwargs}

    if generation_config:
        config_data["generation_config"] = GeminiGenerationConfig.from_dict(
            generation_config
        )

    return GeminiBackendConfig.model_validate(config_data)


def create_openai_backend_config(
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    **kwargs,
) -> OpenAIBackendConfig:
    """Create OpenAI backend configuration with validation."""
    return OpenAIBackendConfig(
        temperature=temperature, max_tokens=max_tokens, top_p=top_p, **kwargs
    )


def create_anthropic_backend_config(
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    **kwargs,
) -> AnthropicBackendConfig:
    """Create Anthropic backend configuration with validation."""
    return AnthropicBackendConfig(
        temperature=temperature, max_tokens=max_tokens, top_p=top_p, **kwargs
    )


def create_backend_configuration(
    backend_type: str,
    extra_body: dict[str, Any] | None = None,
    **backend_specific_config,
) -> BackendConfiguration:
    """Create complete backend configuration with validation."""
    config_data: dict[str, Any] = {
        "backend_type": backend_type,
        "extra_body": extra_body or {},
    }

    if backend_type == "gemini":
        config_data["gemini_config"] = create_gemini_backend_config(
            **backend_specific_config
        )
    elif backend_type == "openai":
        config_data["openai_config"] = create_openai_backend_config(
            **backend_specific_config
        )
    elif backend_type == "anthropic":
        config_data["anthropic_config"] = create_anthropic_backend_config(
            **backend_specific_config
        )

    return BackendConfiguration.model_validate(config_data)
