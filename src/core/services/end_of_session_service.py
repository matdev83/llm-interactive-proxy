"""End-of-Session service implementation.

This service normalizes completion signals and emits End-of-Session events
once per session using atomic database claims and in-memory dedupe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone

from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.events.end_of_session_events import (
    EndOfSessionErrorClassification,
    EndOfSessionSignal,
    RemoteBackendConnectionEndOfSessionEvent,
)
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.interfaces.event_bus_interface import IEventBus

logger = logging.getLogger(__name__)

# Maximum number of session IDs to keep in the in-memory dedupe cache.
# 100,000 UUIDs is roughly ~10-15 MB of memory, providing a large window
# for dedupe without unbounded growth.
MAX_CACHE_SIZE = 100_000

# TTL for fail-open cache entries (~5 minutes as per design.md)
# This ensures entries expire after approximately 5 minutes to prevent
# unbounded growth when DB is unavailable.
FAIL_OPEN_CACHE_TTL_SECONDS = 300  # 5 minutes


class EndOfSessionService(IEndOfSessionService):
    """Service for normalizing completion signals and emitting EoS events.

    This service ensures at-most-once event emission per session by:
    - Using atomic database claims to prevent duplicate emissions
    - Maintaining in-memory cache for hot-path dedupe
    - Respecting configuration toggles (enabled, emit_events)
    - Using bounded dispatch timeout to avoid blocking response finalization
    """

    def __init__(
        self,
        event_bus: IEventBus,
        config: EndOfSessionConfig,
        session_repository: SessionMetricsRepository,
    ) -> None:
        """Initialize the End-of-Session service.

        Args:
            event_bus: Event bus for publishing EoS events
            config: End-of-Session configuration
            session_repository: Repository for session metrics persistence
        """
        self._event_bus = event_bus
        self._config = config
        self._session_repository = session_repository
        # In-memory cache for hot-path dedupe (async-safe LRU via OrderedDict)
        # Cache entries store timestamps for TTL expiration (design.md requires TTL ~5m)
        # Format: {session_id: timestamp}
        self._ended_sessions: OrderedDict[str, float] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def record_signal(self, signal: EndOfSessionSignal) -> None:
        """Normalize a signal and emit EoS event once per request.

        This method processes a completion signal and emits an End-of-Session
        event if configuration allows and the request hasn't already ended.

        Args:
            signal: Normalized completion signal with session and request metadata
        """
        # Validate configuration
        if not self._config.enabled:
            return

        if not self._config.emit_events:
            return

        # Validate required context
        if not signal.session_id:
            logger.warning(
                "EoS signal missing session_id, treating session as active",
                extra={"signal_type": signal.signal_type.value},
            )
            return

        dedupe_key = signal.request_id or signal.session_id

        if await self.has_ended(signal.session_id, signal.request_id):
            return

        emitted_at = datetime.now(timezone.utc)
        signal_type_str = signal.signal_type.value
        reason = signal.reason

        try:
            # Atomic update for session-level aggregates (turn count, etc.)
            claim_succeeded = await self._session_repository.claim_eos_emission(
                session_id=signal.session_id,
                emitted_at=emitted_at,
                signal_type=signal_type_str,
                reason=reason,
            )

            # Only emit event if claim succeeded (prevents duplicate emissions)
            if not claim_succeeded:
                logger.debug(
                    "EoS claim failed for session %s request %s (already claimed), skipping emission",
                    signal.session_id,
                    signal.request_id,
                )
                # Still mark as ended in cache for fast subsequent checks
                await self._mark_ended(dedupe_key)
                return

            await self._mark_ended(dedupe_key)

            error_classification = signal.error_classification
            if (
                signal.termination_category.value == "error"
                and error_classification is None
            ):
                error_classification = EndOfSessionErrorClassification.UNKNOWN_ERROR

            event = RemoteBackendConnectionEndOfSessionEvent(
                session_id=signal.session_id,
                signal_type=signal.signal_type,
                termination_category=signal.termination_category,
                reason=signal.reason,
                error_classification=error_classification,
                error_status_code=signal.error_status_code,
                protocol=signal.protocol,
                request_id=signal.request_id,
                backend=signal.backend,
                timestamp=emitted_at,
            )

            await self._emit_with_timeout(event)

        except Exception as e:
            if await self.has_ended(signal.session_id, signal.request_id):
                return

            logger.error(
                "EoS persistence unavailable for request %s: %s, "
                "emitting event in fail-open mode",
                dedupe_key,
                e,
                exc_info=True,
            )

            await self._mark_ended(dedupe_key)

            error_classification = signal.error_classification
            if (
                signal.termination_category.value == "error"
                and error_classification is None
            ):
                error_classification = EndOfSessionErrorClassification.UNKNOWN_ERROR

            event = RemoteBackendConnectionEndOfSessionEvent(
                session_id=signal.session_id,
                signal_type=signal.signal_type,
                termination_category=signal.termination_category,
                reason=signal.reason,
                error_classification=error_classification,
                error_status_code=signal.error_status_code,
                protocol=signal.protocol,
                request_id=signal.request_id,
                backend=signal.backend,
                timestamp=emitted_at,
            )

            await self._emit_with_timeout(event)

    async def _emit_with_timeout(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Emit event with bounded dispatch timeout."""
        timeout = self._config.dispatch_timeout_seconds

        if timeout <= 0:
            await self._event_bus.publish_nowait(event)
            logger.info(
                "EoS event emitted for session %s request %s (signal_type=%s, category=%s)",
                event.session_id,
                event.request_id,
                event.signal_type.value,
                event.termination_category.value,
            )
            return

        try:
            await asyncio.wait_for(
                asyncio.shield(self._event_bus.publish(event)),
                timeout=timeout,
            )
            logger.info(
                "EoS event emitted for session %s request %s (signal_type=%s, category=%s)",
                event.session_id,
                event.request_id,
                event.signal_type.value,
                event.termination_category.value,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "EoS event dispatch timeout (%.1fs) for request %s, continuing without waiting",
                timeout,
                event.request_id,
                exc_info=True,
            )

    async def has_ended(self, session_id: str, request_id: str | None = None) -> bool:
        """Check if EoS event has already been emitted for this request or session.

        Args:
            session_id: Session identifier
            request_id: Optional request identifier for turn-scoped check

        Returns:
            True if already emitted, False otherwise
        """
        dedupe_key = request_id or session_id
        async with self._cache_lock:
            if dedupe_key not in self._ended_sessions:
                return False

            # Check TTL expiration
            timestamp = self._ended_sessions[dedupe_key]
            if time.monotonic() - timestamp > FAIL_OPEN_CACHE_TTL_SECONDS:
                self._ended_sessions.pop(dedupe_key)
                return False

            return True

    async def _mark_ended(self, key: str) -> None:
        """Mark a request or session as ended in in-memory cache.

        Args:
            key: Deduplication key (request_id or session_id)
        """
        async with self._cache_lock:
            self._prune_expired_entries()

            if key in self._ended_sessions:
                self._ended_sessions.pop(key)

            self._ended_sessions[key] = time.monotonic()

            if len(self._ended_sessions) > MAX_CACHE_SIZE:
                self._ended_sessions.popitem(last=False)

    def _prune_expired_entries(self) -> None:
        """Remove expired entries from cache based on TTL.

        This method is called during cache updates to ensure expired entries
        are removed. Design.md requires TTL ~5m for fail-open dedupe.
        """
        current_time = time.monotonic()
        expired_keys = [
            session_id
            for session_id, timestamp in self._ended_sessions.items()
            if current_time - timestamp > FAIL_OPEN_CACHE_TTL_SECONDS
        ]
        for session_id in expired_keys:
            self._ended_sessions.pop(session_id, None)
