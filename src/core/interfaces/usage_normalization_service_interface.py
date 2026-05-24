"""Interface for usage normalization service.

This interface defines the contract for normalizing provider-specific usage data
into canonical usage records and projecting canonical usage back to protocol-specific formats.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.usage_normalization_context import UsageNormalizationContext
from src.core.domain.usage_payload import UsagePayload
from src.core.domain.usage_summary import UsageSummary


class IUsageNormalizationService(ABC):
    """Service interface for usage normalization.

    Centralizes usage normalization into canonical records and provides
    protocol-specific projection of canonical usage.
    """

    @abstractmethod
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

        Args:
            context: Normalization context with identifiers, protocol, and completion signals
            usage: Optional canonical usage summary
            raw_usage: Optional raw protocol-specific usage payload

        Returns:
            Canonical usage record with normalized fields

        Raises:
            No exceptions raised - fails open with nulls and logs warnings
        """
        ...

    @abstractmethod
    def project_protocol_usage(
        self,
        *,
        canonical: CanonicalUsageRecord,
        existing: UsagePayload | None = None,
    ) -> UsagePayload | None:
        """Project canonical usage into protocol-specific usage payload.

        Merges canonical usage fields into protocol payload without overwriting
        existing non-null values with zeroes or nulls.

        Args:
            canonical: Canonical usage record to project
            existing: Optional existing protocol usage payload to merge into

        Returns:
            Protocol usage payload with merged canonical fields, or None if no usable fields
        """
        ...
