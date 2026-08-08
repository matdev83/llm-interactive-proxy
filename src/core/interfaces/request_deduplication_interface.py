"""Interface for request deduplication service.

This module defines the protocol for request deduplication to prevent
duplicate requests from being sent to backends within a configurable time window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest


class DeduplicationStats(BaseModel):
    """Statistics for request deduplication service."""

    enabled: bool
    window_seconds: float
    cache_size: int
    duplicates_blocked: int
    requests_processed: int
    dedup_rate: float
    extra: dict[str, int] | None = (
        None  # Extended stats (retries_after_error_allowed, etc)
    )


class IRequestDeduplicationService(Protocol):
    """Protocol for request deduplication service with status-aware tracking."""

    async def check_and_register(
        self, request: ChatRequest, session_id: str
    ) -> tuple[bool, str, float | None]:
        """Check if request is a duplicate and register if not.

        Args:
            request: The chat request to check
            session_id: The session identifier

        Returns:
            Tuple of (is_duplicate, content_hash, retry_after_seconds)
            - is_duplicate: True if this is a duplicate within the dedup window
            - content_hash: The computed hash of the request content
            - retry_after_seconds: Suggested backoff for duplicates (seconds) or None
        """
        ...

    async def mark_request_complete(
        self,
        content_hash: str,
        session_id: str,
        status_code: int | None = None,
        client_disconnected: bool = False,
    ) -> None:
        """Mark a request as complete with its final status.

        This enables status-aware deduplication that distinguishes between
        legitimate retries (after 429) and zombie duplicates (after success).

        Args:
            content_hash: The request content hash
            session_id: The session identifier
            status_code: HTTP status code (200, 429, 503, etc) or None
            client_disconnected: Whether client disconnected before completion
        """
        ...

    async def get_request_outcome(
        self, content_hash: str, session_id: str
    ) -> tuple[str, int | None] | None:
        """Return the tracked status and HTTP code for a request, if present."""
        ...

    def get_stats(self) -> DeduplicationStats:
        """Return deduplication statistics.

        Returns:
            DeduplicationStats object with stats including:
            - enabled: Whether deduplication is enabled
            - window_seconds: The dedup window in seconds
            - cache_size: Current number of cached entries
            - duplicates_blocked: Total duplicates blocked
            - requests_processed: Total requests processed
            - dedup_rate: Ratio of duplicates to total requests
            - extra: Extended stats (retries_after_error_allowed, etc)
        """
        ...

    async def cleanup(self) -> int:
        """Force cleanup of expired entries.

        Returns:
            Number of entries removed
        """
        ...
