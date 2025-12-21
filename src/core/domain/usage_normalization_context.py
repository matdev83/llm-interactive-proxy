"""Usage normalization context models.

This module defines the context model used for usage normalization,
carrying request identifiers, protocol, backend/model info, and
completion signals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.domain.usage_canonical_record import (
    UsageCompletionOutcome,
    UsageIncompleteReason,
)
from src.core.interfaces.model_bases import DomainModel

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext


class UsageNormalizationContext(DomainModel):
    """Context for usage normalization.

    Carries all signals needed to build a canonical usage record,
    including request identifiers, protocol, backend/model info,
    and completion outcome signals.

    To build from RequestContext, use the `from_request_context` class method
    which handles request_id precedence resolution per requirements 1.5 and 1.6:
    - First checks RequestContext.request_id
    - Falls back to RequestContext.processing_context.values.request_id
    - Returns None if neither is available
    """

    request_id: str | None = None
    protocol: str | None = None
    backend_type: str | None = None
    model: str | None = None
    is_streaming: bool = False
    completion_outcome: UsageCompletionOutcome | None = None
    incomplete_reason: UsageIncompleteReason | None = None
    cancel_reason: str | None = None
    error_classification: str | None = None
    """Error classification: timeout, backend_error, connection_error, unknown."""

    @classmethod
    def from_request_context(
        cls,
        request_context: RequestContext,
        *,
        is_streaming: bool = False,
        completion_outcome: UsageCompletionOutcome | None = None,
        incomplete_reason: UsageIncompleteReason | None = None,
        cancel_reason: str | None = None,
        error_classification: str | None = None,
    ) -> UsageNormalizationContext:
        """Build UsageNormalizationContext from RequestContext.

        Resolves request_id precedence per requirements 1.5 and 1.6:
        - RequestContext.request_id (primary)
        - RequestContext.processing_context.values.request_id (fallback)
        - None if neither available

        Extracts protocol from RequestContext.extensions.protocol (set by controllers
        per requirements 1.9-1.12).

        Args:
            request_context: Request context with identifiers and metadata
            is_streaming: Whether this is a streaming request
            completion_outcome: Completion outcome for streaming requests
            incomplete_reason: Incomplete reason if outcome is incomplete
            cancel_reason: Cancellation reason from processing context
            error_classification: Error classification from error mapper

        Returns:
            UsageNormalizationContext with resolved identifiers and signals
        """
        # Resolve request_id precedence: RequestContext.request_id, then
        # RequestContext.processing_context.values.request_id, else None
        # (Requirements 1.5, 1.6)
        request_id = request_context.request_id
        if request_id is None and request_context.processing_context is not None:
            request_id = request_context.processing_context.values.get("request_id")

        # Extract protocol from extensions (set by controllers per requirements 1.9-1.12)
        protocol = None
        if "protocol" in request_context.extensions:
            protocol_value = request_context.extensions["protocol"]
            if isinstance(protocol_value, str):
                protocol = protocol_value

        # Extract cancel_reason from processing_context.values if not provided
        if cancel_reason is None and request_context.processing_context is not None:
            cancel_reason = request_context.processing_context.values.get(
                "cancel_reason"
            )

        return cls(
            request_id=request_id,
            protocol=protocol,
            backend_type=request_context.backend,
            model=request_context.effective_model,
            is_streaming=is_streaming,
            completion_outcome=completion_outcome,
            incomplete_reason=incomplete_reason,
            cancel_reason=cancel_reason,
            error_classification=error_classification,
        )
