"""
Domain models for non-forwardable message tagging.

This module defines the core domain concepts for tagging messages as non-forwardable
and filtering them from outbound backend payloads.

Requirements covered:
- 1.1: Tag messages per session (scoped)
- 1.7: Support "never-forward" scope
- 1.8: Support "client-history-only" scope
- 14.1: Bounded memory representation
"""

from __future__ import annotations

from enum import Enum

from pydantic import ConfigDict

from src.core.interfaces.model_bases import DomainModel

# Type alias for message identity (SHA-256 hex digest)
MessageIdentity = str


class NonForwardableTagScope(str, Enum):
    """Scope for non-forwardable message tags.

    Determines when a tagged message must be excluded from outbound backend payloads.
    """

    NEVER_FORWARD = "never_forward"
    """Tagged message is excluded from all outbound backend payloads (regardless of origin)."""

    CLIENT_HISTORY_ONLY = "client_history_only"
    """Tagged message is excluded only when present in client-submitted history.
    
    Messages tagged with this scope may be included when injected by the proxy
    for a backend-call workflow, but must be excluded if later echoed by clients.
    """


class NonForwardableMessageTag(DomainModel):
    """Compact tag record for non-forwardable message identity.

    Stores only fixed-size identity (hash) and scope, without retaining message content.
    This ensures bounded memory usage per session (requirement 14.1).
    """

    model_config = ConfigDict(frozen=True)

    identity: MessageIdentity
    """Deterministic message identity (SHA-256 hex digest)."""

    scope: NonForwardableTagScope
    """Tag scope determining filtering behavior."""

    reason: str
    """Reason for tagging (e.g., 'slash_command', 'command_response', 'steering_injection')."""

    def __eq__(self, other: object) -> bool:
        """Tags are equal if identity and scope match (reason is not part of equality)."""
        if not isinstance(other, NonForwardableMessageTag):
            return False
        return self.identity == other.identity and self.scope == other.scope

    def __hash__(self) -> int:
        """Hash based on identity and scope."""
        return hash((self.identity, self.scope))


__all__ = [
    "MessageIdentity",
    "NonForwardableTagScope",
    "NonForwardableMessageTag",
]
