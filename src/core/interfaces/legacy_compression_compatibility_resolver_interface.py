"""Contract for legacy/dynamic compression compatibility decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.core.services.legacy_compression_compatibility_resolver import (
        ConnectorTruncationCompatibilityDecision,
        ConnectorTruncationCompatibilityDiagnostics,
    )


class ILegacyCompressionCompatibilityResolver(Protocol):
    """Resolve precedence between legacy and dynamic compression controls."""

    def resolve_connector_truncation(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> ConnectorTruncationCompatibilityDecision:
        """Return effective connector-level truncation decision."""
        ...

    def resolve_connector_truncation_with_diagnostics(
        self,
        *,
        connector_max_chars: int | None,
        connector_max_lines: int | None,
        compaction_enabled: bool,
        dynamic_compression_enabled: bool,
    ) -> tuple[
        ConnectorTruncationCompatibilityDecision,
        ConnectorTruncationCompatibilityDiagnostics,
    ]:
        """Return truncation precedence decision plus diagnostics."""
        ...


def create_default_legacy_compression_compatibility_resolver() -> (
    ILegacyCompressionCompatibilityResolver
):
    """Create the default resolver implementation via a core-internal factory.

    Connectors should depend on this interface module rather than importing
    concrete service implementations directly.
    """

    from src.core.services.legacy_compression_compatibility_resolver import (
        LegacyCompressionCompatibilityResolver,
    )

    return LegacyCompressionCompatibilityResolver()
