"""Session key for transport-agnostic session identity.

This module defines SessionKey, a typed key that prevents cross-session leakage
and supports multi-transport isolation for cancellation and End-of-Session scoping.

The SessionKey represents a lifecycle session identity that is stable for a single
request/connection and never shared across concurrent sessions.

See `.kiro/specs/client-end-of-session-handling/design.md` for the complete
specification of session identity mapping and scoping rules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionKey:
    """Transport-agnostic session identity for cancellation and EoS scoping.

    This key represents a lifecycle session that must emit exactly one
    End-of-Session (EoS) event. Cancellation is strictly scoped to this unit.

    Attributes:
        protocol: Transport protocol identifier (e.g., "http").
        primary_id: The lifecycle session identifier for EoS/Cancellation scope.
            For HTTP: Trace ID (unique request ID).
        group_id: Optional grouping key for aggregation (e.g., Conversation ID).
            For HTTP: Conversation ID from headers/body.

    Invariants:
        - primary_id must be non-empty (enforces "missing context => no attribution")
        - SessionKey is immutable and hashable for use as dictionary keys
        - Equality is based on all fields (protocol, primary_id, group_id)

    Example:
        HTTP request:
            SessionKey(
                protocol="http",
                primary_id="trace-abc123",
                group_id="conversation-xyz789"
            )
    """

    protocol: str
    primary_id: str
    group_id: str | None = None

    def __post_init__(self) -> None:
        """Validate that primary_id is non-empty."""
        if not self.primary_id or not self.primary_id.strip():
            raise ValueError("primary_id cannot be empty")
