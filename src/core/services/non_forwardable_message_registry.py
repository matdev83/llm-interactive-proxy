"""
Non-forwardable message registry service implementation.

Stores and queries non-forwardable tags for session lifetime.
Tags are append-only and immutable for the session lifetime.

Requirements: 1.1, 1.3, 1.7, 1.8, 8.3, 8.4, 10.1, 14.1, 14.2, 14.3, 14.4

Note: Requirements 2.5, 3.1, 4.1 are supported by this registry but implemented
in Phase 5 (tagging at sources). This registry provides the storage layer for those features.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from src.core.common.exceptions import NonForwardableTagLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.non_forwardable import (
    MessageIdentity,
    NonForwardableMessageTag,
    NonForwardableTagScope,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageRegistry,
)

logger = logging.getLogger(__name__)


class NonForwardableMessageRegistry(INonForwardableMessageRegistry):
    """Service for storing and querying non-forwardable tags per session.

    Stores tags in-memory with bounded storage per session. Tags are
    append-only and immutable for session lifetime. Deduplication is
    automatic via set operations.
    """

    def __init__(self, app_config: AppConfig) -> None:
        """Initialize registry with configuration.

        Args:
            app_config: Application configuration containing tag limit settings.
        """
        self._app_config = app_config
        # In-memory storage: session_id -> set of NonForwardableMessageTag
        # Using set for automatic deduplication (tags are hashable)
        self._tags_by_session: dict[str, set[NonForwardableMessageTag]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    @property
    def _max_identities_per_session(self) -> int:
        """Get configured maximum identities per session."""
        return self._app_config.non_forwardable_tagging.max_identities_per_session

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
        if not session_id:
            raise ValueError("session_id must be non-empty")

        # Convert identities to list to allow multiple iterations
        identity_list = list(identities)

        # Early return for empty identities list (idempotent operation)
        if not identity_list:
            return

        async with self._lock:
            # Get existing tags for session (create empty set if new session)
            existing_tags = self._tags_by_session.get(session_id, set())

            # Create new tag instances (deduplication happens via set operations)
            new_tags = {
                NonForwardableMessageTag(identity=identity, scope=scope, reason=reason)
                for identity in identity_list
            }

            # Calculate what the new tag count would be after adding
            # Set union automatically handles deduplication
            combined_tags = existing_tags | new_tags
            new_count = len(combined_tags)

            # Check limit before adding (atomic check)
            if new_count > self._max_identities_per_session:
                raise NonForwardableTagLimitExceededError(
                    message=(
                        f"Non-forwardable tag capacity exceeded for session {session_id}. "
                        f"Limit: {self._max_identities_per_session}, "
                        f"Would result in: {new_count} tags"
                    ),
                    session_id=session_id,
                    max_limit=self._max_identities_per_session,
                )

            # Update session tags (monotonic append-only operation)
            self._tags_by_session[session_id] = combined_tags

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Tagged %d identities for session %s (scope=%s, reason=%s). "
                    "Total tags in session: %d",
                    len(new_tags),
                    session_id,
                    scope.value,
                    reason,
                    new_count,
                )

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
        if not session_id:
            raise ValueError("session_id must be non-empty")

        async with self._lock:
            # Get tags for session (empty set if session doesn't exist)
            session_tags = self._tags_by_session.get(session_id, set())

            # Create tag instance to check (reason doesn't matter for lookup)
            lookup_tag = NonForwardableMessageTag(
                identity=identity, scope=scope, reason=""
            )

            # Check if tag exists in session's tag set
            return lookup_tag in session_tags
