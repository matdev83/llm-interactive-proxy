"""
Typed context models for backend request manager processing.

These models provide type-safe context data for request preparation and response handling,
avoiding ad hoc dicts across component boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

# Type alias for streaming context dictionary
# This matches the middleware context pattern used throughout the codebase
# and aligns with design.md specification for IQualityVerifierStreamVerifier
StreamingContext = dict[str, Any]


class StructuredOutputContext(BaseModel):
    """Context for structured output validation."""

    response_schema: Any = Field(..., description="The JSON schema for validation")
    schema_name: str = Field(..., description="Name identifier for the schema")
    request_id: str = Field(..., description="Request identifier for correlation")


class ResponseProcessingContext(BaseModel):
    """Processing context for backend request handlers.

    This model encapsulates all context data needed for processing backend responses,
    including session information, backend/model names, and optional structured output context.
    """

    session_id: str = Field(..., description="Session identifier")
    backend_name: str | None = Field(
        None, description="Backend identifier (e.g., 'openai', 'anthropic')"
    )
    model_name: str | None = Field(None, description="Model identifier")
    client_os: str | None = Field(None, description="Client OS identifier")
    original_request: Any | None = Field(
        None, description="Original backend request (ChatRequest)"
    )
    structured_output: StructuredOutputContext | None = Field(
        None, description="Structured output validation context if applicable"
    )

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True


class ToolCallRetryState(BaseModel):
    """State tracking for tool-call retry coordination.

    This model tracks the current retry attempt and limits for tool-call retry flows.
    """

    retry_count: int = Field(..., ge=0, description="Current retry attempt count")
    max_retries: int = Field(..., ge=0, description="Maximum allowed retries")
    steering_message: str | None = Field(
        None, description="Steering message for retry attempt"
    )
    is_streaming: bool = Field(
        False, description="Whether this retry is for a streaming request"
    )
