"""Usage normalization service.

This service centralizes usage normalization into canonical records and provides
protocol-specific projection of canonical usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
    UsageIncompleteReason,
)
from src.core.domain.usage_normalization_context import UsageNormalizationContext
from src.core.domain.usage_payload import UsagePayload
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.usage_normalization_service_interface import (
    IUsageNormalizationService,
)

if TYPE_CHECKING:
    from src.core.services.usage_calculation_service import UsageCalculationService

logger = logging.getLogger(__name__)


class UsageNormalizationService(IUsageNormalizationService):
    """Service for normalizing usage data into canonical records.

    Converts provider-specific usage data into canonical usage records
    and projects canonical usage back to protocol-specific formats.

    Responsibilities (per design.md):
    - Produce CanonicalUsageRecord from backend usage and request context
    - Preserve provider extensions and set null for unavailable canonical fields
    - Merge canonical usage into protocol usage without overwriting existing values
    - Map incomplete reasons based on streaming cancellation signals and error classifications
    - Fail open when usage data is missing or malformed (Requirement 4.1, 4.3)
    - Log structured warnings with request identifier, backend type, model, protocol,
      and error classification when usage is malformed (Requirement 4.2)

    Note: Request ID precedence resolution (Requirements 1.5, 1.6) is handled by
    UsageNormalizationContext.from_request_context() helper method.
    """

    def __init__(self, calculation_service: UsageCalculationService) -> None:
        """Initialize the normalization service.

        Args:
            calculation_service: Service for token calculation and derivation.
                                 Note: Currently not used in Phase 2 (normalization only).
                                 Reserved for future phases when token recalculation is needed
                                 (e.g., when proxy modifies content and usage must be recalculated).
        """
        self._calculation_service = calculation_service

    async def build_canonical_record(
        self,
        *,
        context: UsageNormalizationContext,
        usage: UsageSummary | None = None,
        raw_usage: UsagePayload | None = None,
    ) -> CanonicalUsageRecord:
        """Build canonical usage record from normalization context and usage data.

        Returns canonical usage with nulls for unavailable fields.
        Preserves provider extensions in the extensions container.

        Implements Requirements:
        - 1.1: Produces canonical usage record when usage metrics are available
        - 1.2: Includes all canonical fields when available from inputs
        - 1.3: Derives total_tokens when both prompt and completion tokens available
        - 1.4: Sets fields to null when unavailable
        - 1.7, 1.8: Maps provider_id and model_id from context
        - 2.2, 2.3: Preserves provider extensions in extensions container
        - 2.4: Normalizes units and naming
        - 3.1, 3.3, 3.4: Resolves completion outcome and incomplete reason
        - 4.1, 4.3: Fails open with nulls when usage data is missing
        - 4.2: Logs structured warnings for malformed usage

        Args:
            context: Normalization context with identifiers, protocol, and completion signals.
                     Should be built using UsageNormalizationContext.from_request_context()
                     to ensure proper request_id precedence resolution (Requirements 1.5, 1.6).
            usage: Optional canonical usage summary
            raw_usage: Optional raw protocol-specific usage payload

        Returns:
            Canonical usage record with normalized fields. Fields that cannot be derived
            from inputs are set to null (Requirement 1.4, 4.1, 4.3).

        Raises:
            No exceptions raised - fails open with nulls and logs warnings (Requirement 4.1, 4.2)
        """
        # Map identifiers from context
        request_id = context.request_id
        protocol = context.protocol
        provider_id = context.backend_type
        model_id = context.model

        # Extract token counts
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        total_tokens: int | None = None
        cost: float | None = None
        extensions: dict[str, Any] = {}

        # Extract from UsageSummary if available
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens
            # Cost may be in extensions
            if "cost" in usage.extensions:
                cost_value = usage.extensions["cost"]
                if isinstance(cost_value, int | float):
                    cost = float(cost_value)
            # Preserve extensions (excluding cost which is extracted to top-level)
            # Requirement 2.2, 2.3: Store provider-specific metrics in extensions container
            # but exclude standard fields that are promoted to top-level
            for key, value in usage.extensions.items():
                if key != "cost":  # Cost is extracted to top-level, not in extensions
                    extensions[key] = value

        # Extract from raw UsagePayload if available (may override or supplement)
        if raw_usage is not None:
            payload = raw_usage.payload
            # Extract tokens if not already set
            if prompt_tokens is None and "prompt_tokens" in payload:
                prompt_val = payload["prompt_tokens"]
                if isinstance(prompt_val, int):
                    prompt_tokens = prompt_val
            if completion_tokens is None and "completion_tokens" in payload:
                completion_val = payload["completion_tokens"]
                if isinstance(completion_val, int):
                    completion_tokens = completion_val
            if total_tokens is None and "total_tokens" in payload:
                total_val = payload["total_tokens"]
                if isinstance(total_val, int):
                    total_tokens = total_val

            # Extract cost if not already set
            if cost is None and "cost" in payload:
                cost_val = payload["cost"]
                if isinstance(cost_val, int | float):
                    cost = float(cost_val)

            # Extract extensions (all non-standard fields)
            standard_fields = {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost",
            }
            for key, value in payload.items():
                if key not in standard_fields:
                    extensions[key] = value

        # Derive total_tokens if both prompt and completion are available
        if (
            prompt_tokens is not None
            and completion_tokens is not None
            and total_tokens is None
        ):
            total_tokens = prompt_tokens + completion_tokens

        # Resolve completion outcome and incomplete reason
        completion_outcome = context.completion_outcome
        incomplete_reason: UsageIncompleteReason | None = None

        if completion_outcome == UsageCompletionOutcome.incomplete:
            incomplete_reason = self._resolve_incomplete_reason(context)

        # Validate and log warnings for malformed usage
        self._validate_and_log_warnings(
            context=context,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        # Build canonical record
        # The model validators will handle total_tokens derivation and incomplete_reason validation
        return CanonicalUsageRecord(
            provider_id=provider_id,
            model_id=model_id,
            request_id=request_id,
            protocol=protocol,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            completion_outcome=completion_outcome,
            incomplete_reason=incomplete_reason,
            extensions=extensions,
        )

    def _resolve_incomplete_reason(
        self, context: UsageNormalizationContext
    ) -> UsageIncompleteReason:
        """Resolve incomplete reason from cancellation signals and error classification.

        Args:
            context: Normalization context with cancellation and error signals

        Returns:
            Incomplete reason enum value
        """
        # Check cancel_reason first
        if context.cancel_reason == "client_disconnect":
            return UsageIncompleteReason.client_disconnect

        if (
            context.cancel_reason in ("stream_cancelled", "user_cancelled")
            and context.error_classification is None
        ):
            return UsageIncompleteReason.upstream_cancelled

        # Check error classification
        if context.error_classification == "timeout":
            return UsageIncompleteReason.timeout

        if context.error_classification in ("backend_error", "connection_error"):
            return UsageIncompleteReason.backend_error

        # Fallback to unknown
        return UsageIncompleteReason.unknown

    def _validate_and_log_warnings(
        self,
        context: UsageNormalizationContext,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
    ) -> None:
        """Validate usage data and log structured warnings for malformed usage.

        Args:
            context: Normalization context for logging
            prompt_tokens: Prompt token count (may be None)
            completion_tokens: Completion token count (may be None)
            total_tokens: Total token count (may be None)
        """
        # Check for malformed usage (e.g., negative tokens, inconsistent totals)
        has_issues = False
        issues: list[str] = []

        if prompt_tokens is not None and prompt_tokens < 0:
            has_issues = True
            issues.append("negative prompt_tokens")

        if completion_tokens is not None and completion_tokens < 0:
            has_issues = True
            issues.append("negative completion_tokens")

        if (
            total_tokens is not None
            and prompt_tokens is not None
            and completion_tokens is not None
        ):
            expected_total = prompt_tokens + completion_tokens
            if total_tokens != expected_total:
                has_issues = True
                issues.append(
                    f"inconsistent total_tokens: expected {expected_total}, got {total_tokens}"
                )

        if has_issues and logger.isEnabledFor(logging.WARNING):
            # Use error_classification from context if available, otherwise "malformed_usage"
            # (Requirement 4.2: structured warning with error classification)
            error_class = (
                context.error_classification
                if context.error_classification is not None
                else "malformed_usage"
            )
            logger.warning(
                "Malformed usage data detected",
                extra={
                    "request_id": context.request_id,
                    "backend_type": context.backend_type,
                    "model": context.model,
                    "protocol": context.protocol,
                    "error_class": error_class,
                    "issues": issues,
                },
            )

    def project_protocol_usage(
        self,
        *,
        canonical: CanonicalUsageRecord,
        existing: UsagePayload | None = None,
    ) -> UsagePayload | None:
        """Project canonical usage into protocol-specific usage payload.

        Merges canonical usage fields into protocol payload without overwriting
        existing non-null values with zeroes or nulls.

        Implements Requirements:
        - 5.2: Populates protocol usage fields from canonical usage record
        - 5.3: Preserves existing public response shapes
        - 5.4: Does not overwrite existing protocol-native usage values with zeroes

        Args:
            canonical: Canonical usage record to project
            existing: Optional existing protocol usage payload to merge into.
                      Existing non-null values are preserved (Requirement 5.4).

        Returns:
            Protocol usage payload with merged canonical fields, or None if no usable fields.
            Returns None only when canonical has no usable fields AND existing is None.
        """
        # Start with existing payload if available, otherwise empty dict
        payload: dict[str, Any] = {}
        if existing is not None:
            payload = dict(existing.payload)

        # Track if we have any usable fields to add
        has_usable_fields = False

        # Merge canonical fields (only if non-null)
        if canonical.prompt_tokens is not None and "prompt_tokens" not in payload:
            payload["prompt_tokens"] = canonical.prompt_tokens
            has_usable_fields = True

        if (
            canonical.completion_tokens is not None
            and "completion_tokens" not in payload
        ):
            payload["completion_tokens"] = canonical.completion_tokens
            has_usable_fields = True

        if canonical.total_tokens is not None and "total_tokens" not in payload:
            payload["total_tokens"] = canonical.total_tokens
            has_usable_fields = True

        if canonical.cost is not None and "cost" not in payload:
            payload["cost"] = canonical.cost
            has_usable_fields = True

        # Merge extensions
        if canonical.extensions:
            for key, value in canonical.extensions.items():
                # Only add if not already present (preserve existing)
                if key not in payload:
                    payload[key] = value
                    has_usable_fields = True

        # Return None if we have no usable fields and no existing payload
        if not has_usable_fields and not existing:
            return None

        return UsagePayload(payload=payload)
