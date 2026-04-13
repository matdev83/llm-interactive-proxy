from __future__ import annotations

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class CanonicalRequestProcessingConfig(DomainModel):
    """Runtime settings for the canonical request-processing pipeline."""

    # Empty stream recovery tuning (operational flexibility)
    empty_stream_recovery_prompt: str = Field(
        default="The previous response was empty, please try again.",
        description="Recovery prompt appended to retry requests when stream produces no content",
    )
    max_empty_stream_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Maximum number of empty stream retry attempts before failing",
    )
