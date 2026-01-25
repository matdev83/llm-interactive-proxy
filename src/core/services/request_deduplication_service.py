"""Request deduplication service implementation.

This module provides a thread-safe request deduplication service that prevents
duplicate requests from being sent to backends within a configurable time window.

The service tracks request completion status to distinguish between:
- Zombie retries (after success or client disconnect) → BLOCKED
- Legitimate retries (after 429, 503, timeouts) → ALLOWED
- Parallel duplicates (while request is in-flight) → BLOCKED
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest

from src.core.interfaces.request_deduplication_interface import DeduplicationStats

logger = logging.getLogger(__name__)


class RequestStatus(str, Enum):
    """Status of a tracked request for deduplication."""

    IN_FLIGHT = "in_flight"  # Request currently processing
    SUCCESS = "success"  # Completed successfully (200, 201)
    RETRIABLE_ERROR = "retriable_error"  # Failed with retry-able error (429, 503, etc)
    CLIENT_DISCONNECT = "client_disconnect"  # Client disconnected before completion


@dataclass
class TrackedRequest:
    """Metadata for a tracked request."""

    timestamp: float
    status: RequestStatus
    status_code: int | None = None


class RequestDeduplicationService:
    """Thread-safe request deduplication with status-aware tracking.

    This service detects and blocks duplicate requests within a configurable
    time window while allowing legitimate retries after errors.

    Key behaviors:
    - Blocks zombie retries after successful completion
    - Blocks parallel duplicate requests (same request in-flight)
    - ALWAYS allows retries after 429/503/timeout (regardless of timing)
    - Blocks retries after client disconnect (zombie pattern)

    Attributes:
        _window_seconds: Time window for duplicate detection
        _enabled: Whether deduplication is enabled
        _max_cache_size: Maximum cache entries before forced cleanup
        _cache: Thread-safe cache mapping cache_key -> TrackedRequest
        _lock: Async lock for thread-safe cache access
    """

    _CLEANUP_INTERVAL_SECONDS = 30.0

    def __init__(
        self,
        window_seconds: float = 3.0,
        enabled: bool = True,
        max_cache_size: int = 10000,
    ) -> None:
        """Initialize the deduplication service.

        Args:
            window_seconds: Time window in seconds for duplicate detection.
                           Set to 0 or negative to disable.
            enabled: Whether deduplication is enabled
            max_cache_size: Maximum cache entries before forced cleanup
        """
        self._window_seconds = window_seconds
        self._enabled = enabled
        self._max_cache_size = max_cache_size

        self._cache: dict[str, TrackedRequest] = {}
        self._lock = asyncio.Lock()

        self._duplicates_blocked = 0
        self._requests_processed = 0
        self._retries_after_error_allowed = 0
        self._last_cleanup_time = time.time()

    def _compute_content_hash(self, request: ChatRequest, session_id: str) -> str:
        """Compute deterministic hash of request content.

        Args:
            request: The chat request
            session_id: The session identifier

        Returns:
            A 32-character hex hash of the request content
        """
        try:
            messages_data: list[dict[str, Any]] = []
            if request.messages:
                for msg in request.messages:
                    if hasattr(msg, "model_dump"):
                        messages_data.append(msg.model_dump())
                    elif isinstance(msg, dict):
                        messages_data.append(msg)
                    else:
                        messages_data.append({"content": str(msg)})

            content: dict[str, Any] = {
                "session_id": session_id,
                "model": request.model,
                "messages": messages_data,
            }

            if hasattr(request, "tools") and request.tools:
                content["tools"] = request.tools

            serialized = json.dumps(content, sort_keys=True, default=str)
            return hashlib.sha256(serialized.encode()).hexdigest()[:32]
        except Exception as e:
            logger.warning("Failed to compute content hash: %s", e, exc_info=True)
            return hashlib.sha256(str(time.time()).encode()).hexdigest()[:32]

    async def check_and_register(
        self, request: ChatRequest, session_id: str
    ) -> tuple[bool, str]:
        """Check if request is a duplicate and register if not.

        This method implements status-aware deduplication:
        - Blocks duplicates while original is in-flight or succeeded
        - ALWAYS allows retries after retriable errors (429, 503, etc)
        - Blocks retries after client disconnect (zombie pattern)

        Args:
            request: The chat request to check
            session_id: The session identifier

        Returns:
            Tuple of (is_duplicate, content_hash)
        """
        if not self._enabled or self._window_seconds <= 0:
            return (False, "")

        content_hash = self._compute_content_hash(request, session_id)
        cache_key = f"{session_id}:{content_hash}"
        current_time = time.time()

        async with self._lock:
            await self._maybe_cleanup_locked(current_time)

            self._requests_processed += 1

            if cache_key in self._cache:
                tracked = self._cache[cache_key]
                age = current_time - tracked.timestamp

                # CRITICAL: Always allow retries after retriable errors (429, 503, etc)
                # regardless of how recent they are. This ensures legitimate retries
                # after rate limits are never blocked.
                if tracked.status == RequestStatus.RETRIABLE_ERROR:
                    self._retries_after_error_allowed += 1
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Allowing retry after %s (status_code=%s): hash=%s session=%s age=%.2fs",
                            tracked.status.value,
                            tracked.status_code,
                            content_hash[:8],
                            session_id,
                            age,
                        )
                    # Register as new in-flight request
                    self._cache[cache_key] = TrackedRequest(
                        timestamp=current_time,
                        status=RequestStatus.IN_FLIGHT,
                    )
                    return (False, content_hash)

                # Check if within deduplication window and status is blockable
                if age < self._window_seconds and tracked.status in (
                    RequestStatus.IN_FLIGHT,
                    RequestStatus.SUCCESS,
                    RequestStatus.CLIENT_DISCONNECT,
                ):
                    # Block duplicates of in-flight, successful, or disconnected requests
                    self._duplicates_blocked += 1
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Duplicate blocked (status=%s): hash=%s session=%s age=%.2fs",
                            tracked.status.value,
                            content_hash[:8],
                            session_id,
                            age,
                        )
                    return (True, content_hash)

                # Outside window or unknown status - treat as new request
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Request expired or status unknown: hash=%s session=%s age=%.2fs",
                        content_hash[:8],
                        session_id,
                        age,
                    )

            # New request or expired - register as in-flight
            self._cache[cache_key] = TrackedRequest(
                timestamp=current_time,
                status=RequestStatus.IN_FLIGHT,
            )
            return (False, content_hash)

    async def mark_request_complete(
        self,
        content_hash: str,
        session_id: str,
        status_code: int | None = None,
        client_disconnected: bool = False,
    ) -> None:
        """Mark a request as complete with its final status.

        This updates the tracked request status to enable smart duplicate detection.

        Args:
            content_hash: The request content hash
            session_id: The session identifier
            status_code: HTTP status code (200, 429, 503, etc) or None
            client_disconnected: Whether client disconnected before completion
        """
        if not self._enabled:
            return

        cache_key = f"{session_id}:{content_hash}"

        async with self._lock:
            if cache_key not in self._cache:
                # Request not tracked (disabled or bypassed)
                return

            tracked = self._cache[cache_key]

            # Determine final status
            if client_disconnected:
                new_status = RequestStatus.CLIENT_DISCONNECT
            elif status_code is not None:
                if status_code in (200, 201, 202, 204):
                    new_status = RequestStatus.SUCCESS
                elif status_code in (429, 503, 502, 504, 408):
                    # Retriable errors: rate limit, service unavailable, timeouts
                    new_status = RequestStatus.RETRIABLE_ERROR
                else:
                    # Non-retriable errors (400, 401, 403, 404, 500, etc)
                    # Treat as success to block duplicates
                    new_status = RequestStatus.SUCCESS
            else:
                # No status code provided - assume success
                new_status = RequestStatus.SUCCESS

            # Update tracked request
            tracked.status = new_status
            tracked.status_code = status_code

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Request completed: hash=%s session=%s status=%s code=%s",
                    content_hash[:8],
                    session_id,
                    new_status.value,
                    status_code,
                )

    async def _maybe_cleanup_locked(self, current_time: float) -> None:
        """Cleanup expired entries (called within lock).

        Args:
            current_time: Current monotonic time
        """
        # Optimize: Only cleanup if interval passed OR cache is significantly over limit (10% buffer)
        # This prevents O(N log N) sorting on every request when cache is full
        size_limit_with_buffer = self._max_cache_size * 1.1
        should_cleanup = (
            current_time - self._last_cleanup_time > self._CLEANUP_INTERVAL_SECONDS
            or len(self._cache) > size_limit_with_buffer
        )

        if not should_cleanup:
            return

        self._last_cleanup_time = current_time
        cutoff = current_time - self._window_seconds

        # First pass: remove expired entries (O(N))
        expired_keys = [
            key for key, tracked in self._cache.items() if tracked.timestamp < cutoff
        ]
        for key in expired_keys:
            del self._cache[key]

        # Second pass: if still over strict limit, remove oldest (O(N log N))
        # This runs rarely because we have a 10% buffer
        if len(self._cache) > self._max_cache_size:
            sorted_entries = sorted(self._cache.items(), key=lambda x: x[1].timestamp)
            to_remove = len(self._cache) - self._max_cache_size
            for key, _ in sorted_entries[:to_remove]:
                del self._cache[key]

        if expired_keys and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Dedup cache cleanup: removed %d expired entries, cache_size=%d",
                len(expired_keys),
                len(self._cache),
            )

    async def cleanup(self) -> int:
        """Force cleanup of expired entries.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            initial_size = len(self._cache)
            cutoff = time.time() - self._window_seconds

            expired_keys = [
                key
                for key, tracked in self._cache.items()
                if tracked.timestamp < cutoff
            ]
            for key in expired_keys:
                del self._cache[key]

            return initial_size - len(self._cache)

    def get_stats(self) -> DeduplicationStats:
        """Return deduplication statistics (non-blocking read).

        Returns:
            DeduplicationStats object with deduplication statistics
        """
        dedup_rate = (
            self._duplicates_blocked / self._requests_processed
            if self._requests_processed > 0
            else 0.0
        )

        # Extended stats
        extra_stats = {
            "retries_after_error_allowed": self._retries_after_error_allowed,
        }

        return DeduplicationStats(
            enabled=self._enabled,
            window_seconds=self._window_seconds,
            cache_size=len(self._cache),
            duplicates_blocked=self._duplicates_blocked,
            requests_processed=self._requests_processed,
            dedup_rate=dedup_rate,
            extra=extra_stats,
        )
