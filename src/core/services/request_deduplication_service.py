"""Request deduplication service implementation.

This module provides a thread-safe request deduplication service that prevents
duplicate requests from being sent to backends within a configurable time window.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest

from src.core.interfaces.request_deduplication_interface import DeduplicationStats

logger = logging.getLogger(__name__)


class RequestDeduplicationService:
    """Thread-safe request deduplication with TTL-based cache.

    This service detects and blocks duplicate requests within a configurable
    time window to prevent unnecessary backend calls caused by client retries.

    Attributes:
        _window_seconds: Time window for duplicate detection
        _enabled: Whether deduplication is enabled
        _max_cache_size: Maximum cache entries before forced cleanup
        _cache: Thread-safe cache mapping cache_key -> timestamp
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

        self._cache: dict[str, float] = {}
        self._lock = asyncio.Lock()

        self._duplicates_blocked = 0
        self._requests_processed = 0
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
                entry_time = self._cache[cache_key]
                if current_time - entry_time < self._window_seconds:
                    self._duplicates_blocked += 1
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Duplicate detected: hash=%s, session=%s, age=%.2fs",
                            content_hash[:8],
                            session_id,
                            current_time - entry_time,
                        )
                    return (True, content_hash)

            self._cache[cache_key] = current_time
            return (False, content_hash)

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
            key for key, timestamp in self._cache.items() if timestamp < cutoff
        ]
        for key in expired_keys:
            del self._cache[key]

        # Second pass: if still over strict limit, remove oldest (O(N log N))
        # This runs rarely because we have a 10% buffer
        if len(self._cache) > self._max_cache_size:
            sorted_entries = sorted(self._cache.items(), key=lambda x: x[1])
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
                key for key, timestamp in self._cache.items() if timestamp < cutoff
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
        return DeduplicationStats(
            enabled=self._enabled,
            window_seconds=self._window_seconds,
            cache_size=len(self._cache),
            duplicates_blocked=self._duplicates_blocked,
            requests_processed=self._requests_processed,
            dedup_rate=dedup_rate,
        )
