"""
Model Capabilities Domain Models

Defines the data structures and interfaces for model capability detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.interfaces.model_bases import InternalDTO


class ModelCapability(str, Enum):
    """Enumeration of model capabilities."""

    # Core capabilities
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"

    # Advanced capabilities
    FUNCTION_CALLING = "function_calling"
    TOOL_USE = "tool_use"
    VISION = "vision"
    AUDIO = "audio"
    VIDEO = "video"
    CODE_INTERPRETER = "code_interpreter"
    WEB_BROWSING = "web_browsing"
    FILE_HANDLING = "file_handling"

    # Response formats
    JSON_MODE = "json_mode"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"

    # Reasoning capabilities
    REASONING = "reasoning"
    CHAIN_OF_THOUGHT = "chain_of_thought"
    SELF_REFLECTION = "self_reflection"


@dataclass
class ModelLimits(InternalDTO):
    """Limits and constraints for a model."""

    max_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    context_window: int | None = None

    # Rate limits
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    requests_per_day: int | None = None

    # File limits
    max_file_size_mb: float | None = None
    max_image_size_mb: float | None = None
    supported_file_types: list[str] = field(default_factory=list)

    # Other constraints
    max_temperature: float = 2.0
    min_temperature: float = 0.0
    max_top_p: float = 1.0
    min_top_p: float = 0.0


@dataclass
class ModelPricing(InternalDTO):
    """Pricing information for a model."""

    # Cost per 1K tokens
    input_cost_per_1k: float | None = None
    output_cost_per_1k: float | None = None

    # Alternative pricing models
    cost_per_request: float | None = None
    cost_per_minute: float | None = None

    # Batch/cached pricing
    cached_input_cost_per_1k: float | None = None
    batch_input_cost_per_1k: float | None = None
    batch_output_cost_per_1k: float | None = None

    currency: str = "USD"

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cached: bool = False,
        batch: bool = False,
    ) -> float:
        """Calculate the cost for a request.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cached: Whether input is cached
            batch: Whether this is a batch request

        Returns:
            Total cost in the specified currency
        """
        total_cost = 0.0

        # Calculate input cost
        if batch and self.batch_input_cost_per_1k:
            total_cost += (input_tokens / 1000) * self.batch_input_cost_per_1k
        elif cached and self.cached_input_cost_per_1k:
            total_cost += (input_tokens / 1000) * self.cached_input_cost_per_1k
        elif self.input_cost_per_1k:
            total_cost += (input_tokens / 1000) * self.input_cost_per_1k

        # Calculate output cost
        if batch and self.batch_output_cost_per_1k:
            total_cost += (output_tokens / 1000) * self.batch_output_cost_per_1k
        elif self.output_cost_per_1k:
            total_cost += (output_tokens / 1000) * self.output_cost_per_1k

        return total_cost


@dataclass
class ModelMetadata(InternalDTO):
    """Metadata about a model."""

    # Basic info
    name: str
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    version: str | None = None
    release_date: str | None = None

    # Model characteristics
    model_type: str | None = None  # e.g., "chat", "instruct", "base"
    architecture: str | None = None  # e.g., "transformer", "mamba"
    parameter_count: str | None = None  # e.g., "175B", "7B"
    training_data_cutoff: str | None = None

    # Links and references
    documentation_url: str | None = None
    model_card_url: str | None = None

    # Tags for categorization
    tags: list[str] = field(default_factory=list)

    # Deprecation info
    is_deprecated: bool = False
    deprecation_date: str | None = None
    replacement_model: str | None = None


@dataclass
class ModelCapabilities(InternalDTO):
    """Complete capability profile for a model."""

    # Model identification
    model_id: str
    backend_type: str

    # Metadata
    metadata: ModelMetadata

    # Capabilities
    capabilities: list[ModelCapability] = field(default_factory=list)

    # Limits and constraints
    limits: ModelLimits = field(default_factory=ModelLimits)

    # Pricing
    pricing: ModelPricing | None = None

    # Supported parameters
    supported_parameters: dict[str, Any] = field(default_factory=dict)

    # Performance characteristics
    average_latency_ms: float | None = None
    tokens_per_second: float | None = None

    def has_capability(self, capability: ModelCapability) -> bool:
        """Check if the model has a specific capability.

        Args:
            capability: The capability to check

        Returns:
            True if the model has the capability
        """
        return capability in self.capabilities

    def supports_parameter(self, parameter: str) -> bool:
        """Check if the model supports a specific parameter.

        Args:
            parameter: The parameter name to check

        Returns:
            True if the parameter is supported
        """
        return parameter in self.supported_parameters

    def get_context_window(self) -> int | None:
        """Get the model's context window size.

        Returns:
            Context window size in tokens, or None if unknown
        """
        return self.limits.context_window or self.limits.max_input_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary representation of the model capabilities
        """
        return {
            "model_id": self.model_id,
            "backend_type": self.backend_type,
            "metadata": {
                "name": self.metadata.name,
                "display_name": self.metadata.display_name,
                "description": self.metadata.description,
                "provider": self.metadata.provider,
                "version": self.metadata.version,
                "release_date": self.metadata.release_date,
                "model_type": self.metadata.model_type,
                "architecture": self.metadata.architecture,
                "parameter_count": self.metadata.parameter_count,
                "training_data_cutoff": self.metadata.training_data_cutoff,
                "documentation_url": self.metadata.documentation_url,
                "model_card_url": self.metadata.model_card_url,
                "tags": self.metadata.tags,
                "is_deprecated": self.metadata.is_deprecated,
                "deprecation_date": self.metadata.deprecation_date,
                "replacement_model": self.metadata.replacement_model,
            },
            "capabilities": [cap.value for cap in self.capabilities],
            "limits": {
                "max_tokens": self.limits.max_tokens,
                "max_input_tokens": self.limits.max_input_tokens,
                "max_output_tokens": self.limits.max_output_tokens,
                "context_window": self.limits.context_window,
                "requests_per_minute": self.limits.requests_per_minute,
                "tokens_per_minute": self.limits.tokens_per_minute,
                "requests_per_day": self.limits.requests_per_day,
                "max_file_size_mb": self.limits.max_file_size_mb,
                "max_image_size_mb": self.limits.max_image_size_mb,
                "supported_file_types": self.limits.supported_file_types,
                "max_temperature": self.limits.max_temperature,
                "min_temperature": self.limits.min_temperature,
                "max_top_p": self.limits.max_top_p,
                "min_top_p": self.limits.min_top_p,
            },
            "pricing": (
                {
                    "input_cost_per_1k": self.pricing.input_cost_per_1k,
                    "output_cost_per_1k": self.pricing.output_cost_per_1k,
                    "cost_per_request": self.pricing.cost_per_request,
                    "cost_per_minute": self.pricing.cost_per_minute,
                    "cached_input_cost_per_1k": self.pricing.cached_input_cost_per_1k,
                    "batch_input_cost_per_1k": self.pricing.batch_input_cost_per_1k,
                    "batch_output_cost_per_1k": self.pricing.batch_output_cost_per_1k,
                    "currency": self.pricing.currency,
                }
                if self.pricing
                else None
            ),
            "supported_parameters": self.supported_parameters,
            "average_latency_ms": self.average_latency_ms,
            "tokens_per_second": self.tokens_per_second,
        }


# Predefined model capability profiles
KNOWN_MODEL_CAPABILITIES = {
    "gpt-4": ModelCapabilities(
        model_id="gpt-4",
        backend_type="openai",
        metadata=ModelMetadata(
            name="gpt-4",
            display_name="GPT-4",
            description="OpenAI's most capable model for complex tasks",
            provider="OpenAI",
            version="gpt-4-0613",
            model_type="chat",
            architecture="transformer",
            parameter_count="~1.76T",
            training_data_cutoff="September 2021",
            tags=["general", "reasoning", "coding", "creative"],
        ),
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.JSON_MODE,
            ModelCapability.STREAMING,
            ModelCapability.REASONING,
        ],
        limits=ModelLimits(
            max_tokens=8192,
            context_window=8192,
            requests_per_minute=200,
            tokens_per_minute=40000,
        ),
        pricing=ModelPricing(
            input_cost_per_1k=0.03,
            output_cost_per_1k=0.06,
        ),
    ),
    "gpt-4-turbo": ModelCapabilities(
        model_id="gpt-4-turbo",
        backend_type="openai",
        metadata=ModelMetadata(
            name="gpt-4-turbo",
            display_name="GPT-4 Turbo",
            description="Faster and more capable GPT-4 with vision",
            provider="OpenAI",
            version="gpt-4-1106-preview",
            model_type="chat",
            architecture="transformer",
            training_data_cutoff="April 2023",
            tags=["general", "reasoning", "coding", "creative", "vision"],
        ),
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
            ModelCapability.JSON_MODE,
            ModelCapability.STREAMING,
            ModelCapability.REASONING,
        ],
        limits=ModelLimits(
            max_tokens=128000,
            context_window=128000,
            requests_per_minute=500,
            tokens_per_minute=150000,
        ),
        pricing=ModelPricing(
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        ),
    ),
    "claude-3-opus": ModelCapabilities(
        model_id="claude-3-opus-20240229",
        backend_type="anthropic",
        metadata=ModelMetadata(
            name="claude-3-opus",
            display_name="Claude 3 Opus",
            description="Anthropic's most powerful model",
            provider="Anthropic",
            version="20240229",
            model_type="chat",
            architecture="transformer",
            training_data_cutoff="August 2023",
            tags=["general", "reasoning", "coding", "creative", "analysis"],
        ),
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.VISION,
            ModelCapability.STREAMING,
            ModelCapability.REASONING,
            ModelCapability.CHAIN_OF_THOUGHT,
        ],
        limits=ModelLimits(
            max_tokens=200000,
            context_window=200000,
            requests_per_minute=50,
            tokens_per_minute=100000,
        ),
        pricing=ModelPricing(
            input_cost_per_1k=0.015,
            output_cost_per_1k=0.075,
        ),
    ),
}
