"""
Data models for Gemini base connector.

This module defines typed data structures used across Gemini connector services
to provide type safety and clear data boundaries.
"""

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any


from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True, order=True)
class TierScore:
    """Score for tier ranking in project discovery.

    Fields are ordered for natural comparison (lexicographical):
    1. is_paid (higher is better)
    2. context_tokens (higher is better)
    3. is_default (higher is better)
    """

    is_paid: int
    context_tokens: int
    is_default: int


class GeminiFunctionDeclaration(BaseModel):
    """Gemini-compatible function declaration."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class RateLimitErrorDetails(BaseModel):
    """Details extracted from a 429 rate limit error."""

    message: str
    error_type: str
    error_code: int | None


class TokenUsage(BaseModel):
    """Token usage statistics extracted from Gemini responses."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class GeminiOAuthCredentials(BaseModel):
    """Typed credential payload for Gemini OAuth connectors.


    This model provides a type-safe representation of OAuth credentials with
    validation and helper methods. It preserves backward compatibility by
    allowing extra fields from provider-specific attributes.

    **Data Flow**: This model serves as the shared data boundary for credentials:
    - Produced by `ICredentialCoordinator` via the `.credentials` property
    - Consumed by `IModelRegistry` for API discovery authentication
    - Consumed by `IHealthCheckService` for health check authentication
    - Consumed by connector context for request execution
    - Can be converted to dict via `.to_dict()` for backward compatibility

    **Service Boundaries**: Provides type safety and validation boundaries between
    credential coordination and other services. Forward-compatible via `extra="allow"`
    to preserve provider-specific fields.

    Attributes:
        access_token: Required OAuth access token.
        refresh_token: Optional refresh token for token renewal.
        expiry_date: Optional token expiry timestamp in epoch milliseconds.
        project_id: Optional cached Google Cloud project ID.
    """

    model_config = ConfigDict(extra="allow")

    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str | None = Field(
        None, description="Refresh token for token renewal"
    )
    expiry_date: int | None = Field(
        None, description="Token expiry timestamp in epoch milliseconds"
    )
    project_id: str | None = Field(None, description="Cached Google Cloud project ID")

    @field_validator("access_token")
    @classmethod
    def validate_access_token(cls, v: str) -> str:
        """Validate that access_token is non-empty."""
        if not v or not isinstance(v, str):
            raise ValueError("access_token must be a non-empty string")
        return v

    @field_validator("refresh_token")
    @classmethod
    def validate_refresh_token(cls, v: str | None) -> str | None:
        """Validate that refresh_token is non-empty if provided."""
        if v is not None and (not isinstance(v, str) or not v):
            raise ValueError("refresh_token must be a non-empty string if provided")
        return v

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: int | None) -> int | None:
        """Validate that expiry_date is a positive integer if provided."""
        if v is not None and (not isinstance(v, int) or v < 0):
            raise ValueError("expiry_date must be a non-negative integer if provided")
        return v

    def is_expired(self, buffer_seconds: float = 60.0) -> bool:
        """Check if the access token is expired or within buffer window.

        Args:
            buffer_seconds: Number of seconds before expiry to consider expired.

        Returns:
            True if token is expired or within buffer window, False otherwise.
        """
        if self.expiry_date is None:
            return False

        current_utc_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        expiry_with_buffer = self.expiry_date - int(buffer_seconds * 1000)
        return current_utc_ms >= expiry_with_buffer

    def has_refresh_token(self) -> bool:
        """Check if refresh token is available.

        Returns:
            True if refresh_token is present and non-empty, False otherwise.
        """
        return self.refresh_token is not None and bool(self.refresh_token)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeminiOAuthCredentials":
        """Create credentials from a dictionary (backward compatibility).

        Args:
            data: Dictionary containing credential fields.

        Returns:
            GeminiOAuthCredentials instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert credentials to dictionary (for existing code paths).

        Returns:
            Dictionary representation of credentials including extra fields.
        """
        return self.model_dump(mode="python", exclude_none=False)
