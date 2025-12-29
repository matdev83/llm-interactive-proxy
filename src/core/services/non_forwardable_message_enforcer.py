"""
Non-forwardable message enforcer service implementation.

Filters messages immediately before backend call and emits telemetry.
Preserves order of remaining messages and does not mutate their content.
Fails closed (raises domain error) when filtering cannot be safely applied.

Requirements: 1.4-1.6, 1.8, 1.11, 4.4, 5.*, 6.*, 7.*, 10.1, 11.1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.common.exceptions import (
    NoForwardableContentError,
    NonForwardableEnforcementError,
)
from src.core.domain.chat import ChatMessage
from src.core.domain.non_forwardable import NonForwardableTagScope
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageEnforcer,
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)

if TYPE_CHECKING:
    from src.core.domain.request_context import RequestContext

logger = logging.getLogger(__name__)

# Extension key for injected message provenance boundary
PROXY_INJECTED_MESSAGES_START_INDEX_KEY = "proxy_injected_messages_start_index"


class NonForwardableMessageEnforcer(INonForwardableMessageEnforcer):
    """Service for filtering non-forwardable messages before backend calls.

    Filters messages recognized as non-forwardable for the session and excludes
    them from outbound payloads. Preserves relative ordering of remaining messages
    and does not mutate their content.
    """

    def __init__(
        self,
        identity_service: INonForwardableMessageIdentityService,
        registry: INonForwardableMessageRegistry,
    ) -> None:
        """Initialize enforcer with dependencies.

        Args:
            identity_service: Service for computing message identities.
            registry: Registry for checking tag status.
        """
        self._identity_service = identity_service
        self._registry = registry

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

        Returns:
            Tuple of (filtered_messages, filtered_count).

        Raises:
            NonForwardableEnforcementError: If internal error occurs during filtering (fail closed).
            NoForwardableContentError: If all forwardable user-provided content is removed.
        """
        if not session_id:
            raise NonForwardableEnforcementError(
                message="session_id must be non-empty",
                details={"session_id": session_id},
            )

        if not messages:
            return ([], 0)

        try:
            # Extract provenance boundary if present
            injected_start_index = self._extract_provenance_boundary(
                context, len(messages)
            )

            # Initialize variables to satisfy type checker
            filtered_client_history: list[ChatMessage] = []
            client_history: list[ChatMessage] = []
            filtered_injected: list[ChatMessage] = []

            if injected_start_index is not None:
                # Split messages into client history and injected segments
                client_history = messages[:injected_start_index]
                injected_messages = messages[injected_start_index:]

                # Filter client history against both scopes
                filtered_client_history, client_filtered_count = (
                    await self._filter_message_segment(
                        session_id=session_id,
                        messages=client_history,
                        filter_client_history_only=True,
                    )
                )

                # Filter injected messages against never_forward only
                filtered_injected, injected_filtered_count = (
                    await self._filter_message_segment(
                        session_id=session_id,
                        messages=injected_messages,
                        filter_client_history_only=False,
                    )
                )

                # Combine filtered segments preserving order
                filtered_messages = filtered_client_history + filtered_injected
                total_filtered_count = client_filtered_count + injected_filtered_count
            else:
                # No provenance boundary: filter all messages against both scopes
                filtered_messages, total_filtered_count = (
                    await self._filter_message_segment(
                        session_id=session_id,
                        messages=messages,
                        filter_client_history_only=True,
                    )
                )

            # Check if all forwardable user-provided content was removed
            # Requirement 5.3: "user-provided content" means client history, not injected messages
            # Requirement 4.4: Injected messages should be included for the current call
            if injected_start_index is not None:
                # Validate only client history for user-provided content
                # If client history had user content but it's all filtered, AND no injected messages remain,
                # raise error. If injected messages remain, allow it (requirement 4.4).
                if not filtered_injected:
                    self._validate_forwardable_content(
                        filtered_client_history, client_history
                    )
            else:
                # No provenance boundary: validate all messages for user-provided content
                self._validate_forwardable_content(filtered_messages, messages)

            # Emit telemetry
            self._emit_filtering_telemetry(
                session_id=session_id,
                context=context,
                filtered_count=total_filtered_count,
                original_count=len(messages),
            )

            return (filtered_messages, total_filtered_count)

        except (NoForwardableContentError, NonForwardableEnforcementError):
            # Re-raise domain errors as-is
            raise
        except Exception as e:
            # Wrap unexpected errors as NonForwardableEnforcementError (fail closed)
            raise NonForwardableEnforcementError(
                message=f"Internal error during non-forwardable filtering: {e}",
                details={"session_id": session_id, "error_type": type(e).__name__},
            ) from e

    def _extract_provenance_boundary(
        self, context: RequestContext | None, message_count: int
    ) -> int | None:
        """Extract and validate provenance boundary from context.

        Args:
            context: Optional request context.
            message_count: Total number of messages.

        Returns:
            Start index for injected messages, or None if not present.

        Raises:
            NonForwardableEnforcementError: If boundary is invalid.
        """
        if context is None:
            return None

        extensions = context.extensions
        if not extensions:
            return None

        boundary_value = extensions.get(PROXY_INJECTED_MESSAGES_START_INDEX_KEY)
        if boundary_value is None:
            return None

        # Validate boundary is an integer
        if not isinstance(boundary_value, int):
            raise NonForwardableEnforcementError(
                message=(
                    f"Invalid provenance boundary: expected integer, "
                    f"got {type(boundary_value).__name__}"
                ),
                details={"boundary_value": str(boundary_value)},
            )

        # Validate boundary is in valid range
        if boundary_value < 0 or boundary_value > message_count:
            raise NonForwardableEnforcementError(
                message=(
                    f"Invalid provenance boundary: {boundary_value} "
                    f"must be in range [0, {message_count}]"
                ),
                details={
                    "boundary_value": boundary_value,
                    "message_count": message_count,
                },
            )

        return boundary_value

    async def _filter_message_segment(
        self,
        *,
        session_id: str,
        messages: list[ChatMessage],
        filter_client_history_only: bool,
    ) -> tuple[list[ChatMessage], int]:
        """Filter a segment of messages based on tag scopes.

        Args:
            session_id: Session identifier for tag lookup.
            messages: Messages to filter.
            filter_client_history_only: If True, filter against both scopes.
                If False, filter against never_forward only.

        Returns:
            Tuple of (filtered_messages, filtered_count).
        """
        if not messages:
            return ([], 0)

        filtered: list[ChatMessage] = []
        filtered_count = 0

        for message in messages:
            try:
                # Compute identity for message
                identity = self._identity_service.compute_identity(message)

                # Check if message should be filtered
                should_filter = False

                # Always check never_forward scope
                is_never_forward = await self._registry.is_tagged(
                    session_id=session_id,
                    identity=identity,
                    scope=NonForwardableTagScope.NEVER_FORWARD,
                )

                if is_never_forward:
                    should_filter = True
                elif filter_client_history_only:
                    # Also check client_history_only scope for client history
                    is_client_history_only = await self._registry.is_tagged(
                        session_id=session_id,
                        identity=identity,
                        scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
                    )
                    if is_client_history_only:
                        should_filter = True

                if not should_filter:
                    # Message passes through (preserve order, no mutation)
                    filtered.append(message)
                else:
                    filtered_count += 1

            except Exception as e:
                # Fail closed on any lookup error
                raise NonForwardableEnforcementError(
                    message=f"Error checking tag status for message: {e}",
                    details={"session_id": session_id, "error_type": type(e).__name__},
                ) from e

        return (filtered, filtered_count)

    def _validate_forwardable_content(
        self, filtered_messages: list[ChatMessage], original_messages: list[ChatMessage]
    ) -> None:
        """Validate that at least some forwardable user-provided content remains.

        Args:
            filtered_messages: Messages after filtering.
            original_messages: Original messages before filtering.

        Raises:
            NoForwardableContentError: If all forwardable user-provided content was removed.
        """
        # Check if any user messages remain in filtered list
        has_user_content = any(
            msg.role == "user" and self._has_content(msg) for msg in filtered_messages
        )

        # Check if original had user content
        original_has_user_content = any(
            msg.role == "user" and self._has_content(msg) for msg in original_messages
        )

        # If original had user content but filtered doesn't have any user content, raise error
        # Note: We allow non-user messages (like system messages) to pass through,
        # but if original had user content and filtered doesn't, that's an error
        if original_has_user_content and not has_user_content:
            raise NoForwardableContentError(
                message="All forwardable user-provided content was removed by filtering",
                details={
                    "original_message_count": len(original_messages),
                    "filtered_message_count": len(filtered_messages),
                },
            )

    @staticmethod
    def _has_content(message: ChatMessage) -> bool:
        """Check if message has non-empty content.

        Args:
            message: Message to check.

        Returns:
            True if message has content, False otherwise.
        """
        if message.content is None:
            return False

        if isinstance(message.content, str):
            return bool(message.content.strip())

        if isinstance(message.content, list):
            return len(message.content) > 0

        return bool(message.content)

    def _emit_filtering_telemetry(
        self,
        *,
        session_id: str,
        context: RequestContext | None,
        filtered_count: int,
        original_count: int,
    ) -> None:
        """Emit structured telemetry for filtering decisions.

        Args:
            session_id: Session identifier.
            context: Optional request context for correlation ID.
            filtered_count: Number of messages filtered.
            original_count: Original number of messages.
        """
        # Extract correlation ID from context if available
        correlation_id: str | None = None
        if context is not None:
            correlation_id = getattr(context, "request_id", None)

        # Log at INFO level when messages are filtered, DEBUG otherwise
        if filtered_count > 0:
            logger.info(
                "Non-forwardable filtering applied: %d messages filtered out of %d",
                filtered_count,
                original_count,
                extra={
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "filtered_count": filtered_count,
                    "original_count": original_count,
                },
            )
        else:
            logger.debug(
                "Non-forwardable filtering: no messages filtered",
                extra={
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "original_count": original_count,
                },
            )
