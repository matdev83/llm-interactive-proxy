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


class IRequestDeduplicationService(Protocol):
    """Protocol for request deduplication service."""

    async def check_and_register(
        self, request: ChatRequest, session_id: str
    ) -> tuple[bool, str]:
        """Check if request is a duplicate and register if not.

        Args:
            request: The chat request to check
            session_id: The session identifier

        Returns:
            Tuple of (is_duplicate, content_hash)
            - is_duplicate: True if this is a duplicate within the dedup window
            - content_hash: The computed hash of the request content
        """
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
        """
        ...

    async def cleanup(self) -> int:
        """Force cleanup of expired entries.

        Returns:
            Number of entries removed
        """
        ...
