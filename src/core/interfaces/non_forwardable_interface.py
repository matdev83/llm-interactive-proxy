"""
Service interfaces for non-forwardable message tagging.

This module defines the contracts for identity computation, tag registry,
and message filtering services.

Requirements covered:
- 1.2: Deterministic message identity
- 1.3: Tags immutable for session lifetime
- 1.4: Recognize tagged messages on history resend
- 1.9: Identity excludes client metadata
- 1.10: Identity stable after request normalization
- 7.3: Fail closed on indeterminate match
- 10.1: Fail closed on internal error
- 12.1: Resist spoofing/forgery
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from src.core.domain.chat import ChatMessage
from src.core.domain.non_forwardable import (
    MessageIdentity,
    NonForwardableTagScope,
)
from src.core.domain.request_context import RequestContext


class INonForwardableMessageIdentityService(ABC):
    """Interface for computing deterministic message identity.

    Computes a stable, deterministic identity for a message that can be used
    to recognize the same message when it appears in client-submitted history.
    Identity computation must not rely on client-provided metadata or transport-specific
    fields that may not round-trip through clients.
    """

    @abstractmethod
    def compute_identity(self, message: ChatMessage) -> MessageIdentity:
        """Compute deterministic identity for a message.

        The identity must be stable for equivalent messages within the session
        and must not depend on client metadata or transport-specific fields.

        Args:
            message: The message to compute identity for (must be validated domain ChatMessage).

        Returns:
            Deterministic identity string (SHA-256 hex digest).

        Preconditions:
            - message is a validated domain ChatMessage
        Postconditions:
            - returned identity is stable for equivalent messages within the session
            - identity does not include client metadata or transport-specific fields
        """
        ...


class INonForwardableMessageRegistry(ABC):
    """Interface for session-scoped non-forwardable tag storage and lookup.

    Stores and queries non-forwardable tags for a session lifetime.
    Tags are append-only and immutable for the session lifetime.
    """

    @abstractmethod
    async def tag_identities(
        self,
        session_id: str,
        identities: Iterable[MessageIdentity],
        *,
        scope: NonForwardableTagScope,
        reason: str,
    ) -> None:
        """Persist tags for the given identities in the session.

        Tags are append-only and immutable for session lifetime.
        Re-tagging the same identity+scope is idempotent and does not increase stored state.

        Args:
            session_id: Session identifier for tag scoping.
            identities: Iterable of message identities to tag.
            scope: Tag scope determining filtering behavior.
            reason: Reason for tagging (e.g., 'slash_command', 'command_response', 'steering_injection').

        Raises:
            NonForwardableTagLimitExceededError: If tagging would exceed the configured per-session limit.

        Preconditions:
            - session_id is non-empty
            - identities are valid MessageIdentity values
        Postconditions:
            - Tags are persisted for session lifetime
            - Tags are monotonic (append-only) and never removed within session lifetime
            - Re-tagging same identity+scope does not increase stored state
        """
        ...

    @abstractmethod
    async def is_tagged(
        self,
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        """Check if an identity is tagged for the given session and scope.

        Args:
            session_id: Session identifier for tag lookup.
            identity: Message identity to check.
            scope: Tag scope to check.

        Returns:
            True if identity is tagged for the session and scope, False otherwise.

        Preconditions:
            - session_id is non-empty
            - identity is a valid MessageIdentity
        """
        ...


class INonForwardableMessageEnforcer(ABC):
    """Interface for filtering non-forwardable messages before backend calls.

    Filters messages immediately before backend call and emits telemetry.
    Must preserve order of remaining messages and not mutate their content.
    Must fail closed (raise domain error) when filtering cannot be safely applied.
    """

    @abstractmethod
    async def filter_messages(
        self,
        *,
        session_id: str,
        messages: list[ChatMessage],
        context: RequestContext | None = None,
    ) -> tuple[list[ChatMessage], int]:
        """Filter non-forwardable messages from the message list.

        Filters messages recognized as non-forwardable for the session and excludes
        them from outbound payloads. Preserves relative ordering of remaining messages
        and does not mutate their content.

        Args:
            session_id: Session identifier for tag lookup (must be resolved).
            messages: List of messages to filter (must be validated domain messages).
            context: Optional request context for provenance boundary (injected messages).
                When provided and contains `extensions["proxy_injected_messages_start_index"]`,
                the enforcer splits messages into client-submitted history (before index) and
                proxy-injected messages (at/after index). Client history is filtered against
                both scopes; injected messages are filtered against `never_forward` only.
                The extension value must be an integer in range [0, len(messages)].

        Returns:
            Tuple of (filtered_messages, filtered_count).

        Raises:
            NonForwardableEnforcementError: If internal error occurs during filtering (fail closed).
            NoForwardableContentError: If all forwardable user-provided content is removed.

        Preconditions:
            - session_id is resolved and non-empty
            - messages are validated domain ChatMessage instances
        Postconditions:
            - Returns message list with order preserved and no content mutation
            - Filtered messages are excluded from returned list
            - Filtered count reflects number of messages removed
        """
        ...


__all__ = [
    "INonForwardableMessageIdentityService",
    "INonForwardableMessageRegistry",
    "INonForwardableMessageEnforcer",
]
