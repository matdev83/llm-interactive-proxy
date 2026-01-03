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
        """Normalize a signal and emit EoS event once per session.

        This method processes a completion signal and emits an End-of-Session
        event if configuration allows and the session hasn't already ended.

        Args:
            signal: Normalized completion signal with session metadata
        """
        # Validate configuration
        if not self._config.enabled:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS detection disabled, skipping signal for session %s",
                    signal.session_id,
                )
            return

        if not self._config.emit_events:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS event emission disabled, skipping emission for session %s",
                    signal.session_id,
                )
            return

        # Validate required context
        if not signal.session_id:
            logger.warning(
                "EoS signal missing session_id, treating session as active",
                extra={"signal_type": signal.signal_type.value},
            )
            return

        # Fast-path dedupe check (in-memory cache)
        if await self.has_ended(signal.session_id):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Session %s already ended (in-memory cache), skipping emission",
                    signal.session_id,
                )
            return

        # Attempt atomic DB claim
        emitted_at = datetime.now(timezone.utc)
        signal_type_str = signal.signal_type.value
        reason = signal.reason

        try:
            claim_succeeded = await self._session_repository.claim_eos_emission(
                session_id=signal.session_id,
                emitted_at=emitted_at,
                signal_type=signal_type_str,
                reason=reason,
            )

            if not claim_succeeded:
                # Another caller already claimed emission (or session doesn't exist)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "EoS emission already claimed for session %s, skipping",
                        signal.session_id,
                    )
                # Update cache for future fast-path checks
                await self._mark_ended(signal.session_id)
                return

            # Claim succeeded - emit event
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "EoS emission claimed for session %s (signal: %s)",
                    signal.session_id,
                    signal_type_str,
                    extra={
                        "session_id": signal.session_id,
                        "signal_type": signal_type_str,
                        "termination_category": signal.termination_category.value,
                    },
                )

            # Update cache immediately after successful claim
            await self._mark_ended(signal.session_id)

            # Determine error classification (default to unknown_error for error terminations)
            error_classification = signal.error_classification
            if (
                signal.termination_category.value == "error"
                and error_classification is None
            ):
                error_classification = EndOfSessionErrorClassification.UNKNOWN_ERROR
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Missing error classification for error termination, defaulting to unknown_error for session %s",
                        signal.session_id,
                    )

            # Create and emit event
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
                timestamp=emitted_at,  # Use the actual emission time, not signal observation time
            )

            # Emit with bounded dispatch timeout
            await self._emit_with_timeout(event)

        except Exception as e:
            # Fail-open: if DB claim failed, still emit EoS using in-memory dedupe
            # This ensures EoS events are emitted even when persistence is unavailable
            # Check in-memory cache to preserve "at most once per session" behavior
            if await self.has_ended(signal.session_id):
                # Already emitted in fail-open mode, skip
                logger.debug(
                    "EoS already emitted (fail-open cache) for session %s, skipping duplicate",
                    signal.session_id,
                    extra={
                        "session_id": signal.session_id,
                        "signal_type": signal_type_str,
                        "error_code": "EOS_FAIL_OPEN_DEDUPE",
                    },
                )
                return

            # Log high-signal persistence-unavailable diagnostic
            logger.error(
                "EoS persistence unavailable for session %s: %s, "
                "emitting event in fail-open mode (in-process dedupe only)",
                signal.session_id,
                e,
                exc_info=True,
                extra={
                    "session_id": signal.session_id,
                    "signal_type": signal_type_str,
                    "error_code": "EOS_PERSISTENCE_UNAVAILABLE",
                },
            )

            # Mark as ended in cache before emitting to prevent race conditions
            await self._mark_ended(signal.session_id)

            # Determine error classification (default to unknown_error for error terminations)
            error_classification = signal.error_classification
            if (
                signal.termination_category.value == "error"
                and error_classification is None
            ):
                error_classification = EndOfSessionErrorClassification.UNKNOWN_ERROR

            # Create and emit event directly (bypassing DB claim)
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

            # Emit with bounded dispatch timeout
            await self._emit_with_timeout(event)

    async def _emit_with_timeout(
        self, event: RemoteBackendConnectionEndOfSessionEvent
    ) -> None:
        """Emit event with bounded dispatch timeout.

        If timeout is zero/disabled, use publish_nowait for fire-and-forget.
        Otherwise, wrap publish in asyncio.wait_for with asyncio.shield to
        stop waiting after timeout without canceling in-flight handlers.

        Args:
            event: EoS event to emit
        """
        timeout = self._config.dispatch_timeout_seconds

        if timeout <= 0:
            # Fire-and-forget mode
            await self._event_bus.publish_nowait(event)
            # Log event emission at INFO level per NFR 3 (observability)
            logger.info(
                "EoS event emitted for session %s (signal_type=%s, category=%s)",
                event.session_id,
                event.signal_type.value,
                event.termination_category.value,
                extra={
                    "session_id": event.session_id,
                    "signal_type": event.signal_type.value,
                    "termination_category": event.termination_category.value,
                    "error_classification": (
                        event.error_classification.value
                        if event.error_classification
                        else None
                    ),
                },
            )
            return

        # Bounded wait mode
        try:
            # Use shield to prevent cancellation of in-flight handlers
            await asyncio.wait_for(
                asyncio.shield(self._event_bus.publish(event)),
                timeout=timeout,
            )
            # Log event emission at INFO level per NFR 3 (observability)
            logger.info(
                "EoS event emitted for session %s (signal_type=%s, category=%s)",
                event.session_id,
                event.signal_type.value,
                event.termination_category.value,
                extra={
                    "session_id": event.session_id,
                    "signal_type": event.signal_type.value,
                    "termination_category": event.termination_category.value,
                    "error_classification": (
                        event.error_classification.value
                        if event.error_classification
                        else None
                    ),
                },
            )
        except asyncio.TimeoutError:
            # Timeout reached - stop waiting but don't cancel handlers
            logger.warning(
                "EoS event dispatch timeout (%.1fs) for session %s, continuing without waiting",
                timeout,
                event.session_id,
                exc_info=True,
                extra={
                    "session_id": event.session_id,
                    "timeout_seconds": timeout,
                },
            )
            # Note: Handlers continue running in background due to shield

    async def has_ended(self, session_id: str) -> bool:
        """Check if session has already ended (hot-path dedupe).

        This provides a quick filter before attempting the atomic DB claim.

        Args:
            session_id: Session identifier to check

        Returns:
            True if session has ended (EoS event emitted) and cache entry is valid, False otherwise
        """
        async with self._cache_lock:
            if session_id not in self._ended_sessions:
                return False

            # Check TTL expiration (design.md requires TTL ~5m for fail-open dedupe)
            timestamp = self._ended_sessions[session_id]
            if time.monotonic() - timestamp > FAIL_OPEN_CACHE_TTL_SECONDS:
                # Entry expired, remove it
                self._ended_sessions.pop(session_id)
                return False

            return True

    async def _mark_ended(self, session_id: str) -> None:
        """Mark session as ended in in-memory cache.

        This updates the LRU cache with TTL tracking, moving the session to the end
        (most recently used). If cache size exceeds MAX_CACHE_SIZE, the oldest item
        is removed. Entries expire after TTL (~5m) as required by design.md.

        Args:
            session_id: Session identifier to mark
        """
        async with self._cache_lock:
            # Prune expired entries first
            self._prune_expired_entries()

            # If session is already in cache, remove it first to update position (LRU)
            if session_id in self._ended_sessions:
                self._ended_sessions.pop(session_id)

            # Add to end (most recently used) with current timestamp for TTL
            self._ended_sessions[session_id] = time.monotonic()

            # Evict oldest if limit exceeded
            if len(self._ended_sessions) > MAX_CACHE_SIZE:
                # Pop first item (oldest)
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
