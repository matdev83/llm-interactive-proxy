"""Canonical usage record models.

This module defines the canonical usage record contract with normalized
usage metrics, completion outcomes, and provider extensions.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator
from pydantic.types import JsonValue

from src.core.interfaces.model_bases import DomainModel


class UsageCompletionOutcome(str, Enum):
    """Completion outcome for usage records."""

    complete = "complete"
    incomplete = "incomplete"


class UsageIncompleteReason(str, Enum):
    """Reason for incomplete completion."""

    client_disconnect = "client_disconnect"
    backend_error = "backend_error"
    timeout = "timeout"
    upstream_cancelled = "upstream_cancelled"
    unknown = "unknown"


class CanonicalUsageRecord(DomainModel):
    """Canonical usage record with normalized fields.

    Represents usage metrics normalized across protocols and backends.
    Fields that cannot be derived from inputs are set to null.
    """

    provider_id: str | None = None
    model_id: str | None = None
    request_id: str | None = None
    protocol: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    completion_outcome: UsageCompletionOutcome | None = None
    incomplete_reason: UsageIncompleteReason | None = None
    extensions: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_incomplete_reason(self) -> CanonicalUsageRecord:
        """Validate that incomplete_reason is only set when completion_outcome is incomplete."""
        if (
            self.incomplete_reason is not None
            and self.completion_outcome != UsageCompletionOutcome.incomplete
        ):
            raise ValueError(
                "incomplete_reason can only be set when completion_outcome is incomplete"
            )
        return self

    @model_validator(mode="after")
    def derive_total_tokens(self) -> CanonicalUsageRecord:
        """Derive total_tokens when both prompt and completion are available."""
        if (
            self.prompt_tokens is not None
            and self.completion_tokens is not None
            and self.total_tokens is None
        ):
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self
