"""
Pydantic models for Gemini OAuth Personal connector response metadata.

This module defines the data structures for Gemini response metadata,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


class GeminiUsageInfo(BaseModel):
    """Gemini API usage information."""

    prompt_tokens: int = Field(ge=0, description="Number of tokens in the prompt")
    completion_tokens: int = Field(
        ge=0, description="Number of tokens in the completion"
    )
    total_tokens: int = Field(ge=0, description="Total number of tokens used")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by usage tracking systems."""
        return super().model_dump(**kwargs)


class GeminiModelInfo(BaseModel):
    """Gemini model information."""

    name: str = Field(description="Model name")
    version: str | None = Field(default=None, description="Model version")
    display_name: str | None = Field(
        default=None, description="Human-readable model name"
    )
    description: str | None = Field(default=None, description="Model description")
    input_token_limit: int | None = Field(
        default=None, description="Maximum input tokens"
    )
    output_token_limit: int | None = Field(
        default=None, description="Maximum output tokens"
    )
    supported_generation_methods: list | None = Field(
        default=None, description="Supported generation methods"
    )
    temperature: float | None = Field(default=None, description="Default temperature")
    top_p: float | None = Field(default=None, description="Default top_p")
    top_k: int | None = Field(default=None, description="Default top_k")


class GeminiResponseHeaders(BaseModel):
    """Gemini API response headers."""

    content_type: str | None = Field(default=None, description="Response content type")
    date: str | None = Field(default=None, description="Response date")
    server: str | None = Field(default=None, description="Server information")
    x_request_id: str | None = Field(
        default=None, description="Request ID for tracking"
    )
    x_ratelimit_remaining: str | None = Field(
        default=None, description="Remaining rate limit"
    )
    x_ratelimit_reset: str | None = Field(
        default=None, description="Rate limit reset time"
    )

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by HTTP response systems."""
        result = super().model_dump(**kwargs)
        # Remove None values for cleaner output
        return {k: v for k, v in result.items() if v is not None}


class GeminiGenerationConfig(BaseModel):
    """Gemini generation configuration metadata."""

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

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format expected by Gemini API."""
        result = super().model_dump(**kwargs)
        # Remove None values for cleaner API calls
        return {k: v for k, v in result.items() if v is not None}


class GeminiResponseMetadata(BaseModel):
    """Complete Gemini response metadata."""

    model: str = Field(description="Model name used for the request")
    id: str | None = Field(default=None, description="Response ID")
    created: str | None = Field(default=None, description="Response creation timestamp")
    usage: GeminiUsageInfo | None = Field(
        default=None, description="Token usage information"
    )
    model_info: GeminiModelInfo | None = Field(
        default=None, description="Model information"
    )
    headers: GeminiResponseHeaders | None = Field(
        default=None, description="Response headers"
    )
    generation_config: GeminiGenerationConfig | None = Field(
        default=None, description="Generation configuration used"
    )
    backend: str = Field(default="gemini", description="Backend identifier")
    key_name: str | None = Field(default=None, description="API key name used")
    status_code: int = Field(default=200, description="HTTP status code")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """
        Convert to dictionary format expected by response systems.

        Returns the metadata in the expected format:
        {
            "model": str,
            "id": str,
            "created": str,
            "usage": {...},
            "model_info": {...},
            "headers": {...},
            "generation_config": {...},
            "backend": str,
            "key_name": str,
            "status_code": int
        }
        """
        return super().model_dump(**kwargs)


class GeminiStreamingMetadata(BaseModel):
    """Metadata for streaming Gemini responses."""

    chunk_index: int = Field(ge=0, description="Index of the current chunk")
    is_final: bool = Field(description="Whether this is the final chunk")
    accumulated_content: str = Field(
        default="", description="Accumulated content so far"
    )
    partial_usage: GeminiUsageInfo | None = Field(
        default=None, description="Partial usage information"
    )

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Convert to dictionary format for streaming systems."""
        return super().model_dump(**kwargs)


# Factory functions for creating Gemini metadata
def create_gemini_usage_info(
    prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int | None = None
) -> GeminiUsageInfo:
    """Create Gemini usage information with automatic total calculation."""
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens

    return GeminiUsageInfo(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def create_gemini_response_metadata(
    model: str,
    usage: GeminiUsageInfo | None = None,
    id: str | None = None,
    created: str | None = None,
    key_name: str | None = None,
    status_code: int = 200,
    **kwargs,
) -> GeminiResponseMetadata:
    """Create Gemini response metadata with common defaults."""
    return GeminiResponseMetadata(
        model=model,
        id=id,
        created=created,
        usage=usage,
        key_name=key_name,
        status_code=status_code,
        **kwargs,
    )


def create_gemini_generation_config(
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    max_output_tokens: int | None = None,
    **kwargs,
) -> GeminiGenerationConfig:
    """Create Gemini generation configuration with validation."""
    return GeminiGenerationConfig(
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        max_output_tokens=max_output_tokens,
        **kwargs,
    )


def create_gemini_model_info(
    name: str, version: str | None = None, display_name: str | None = None, **kwargs
) -> GeminiModelInfo:
    """Create Gemini model information."""
    return GeminiModelInfo(
        name=name, version=version, display_name=display_name, **kwargs
    )
