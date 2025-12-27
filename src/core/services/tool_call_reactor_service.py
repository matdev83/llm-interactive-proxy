"""
Tool Call Reactor Service.

This module implements the core tool call reactor service that manages
tool call handlers and orchestrates their execution.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from src.core.common.exceptions import ToolCallReactorError
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    IToolCallHistoryTracker,
    IToolCallReactor,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


class ToolCallReactorService(IToolCallReactor):
    """Core tool call reactor service implementation.

    This service manages a collection of tool call handlers and orchestrates
    their execution when tool calls are detected in LLM responses.
    """

    _MAX_ARGUMENT_SNAPSHOT_BYTES = 16 * 1024
    _SNAPSHOT_WARNING_KEY = "__proxy_warning__"
    _SNAPSHOT_WARNING_VALUE = "tool_arguments_snapshot_omitted"
    _SNAPSHOT_REASON_KEY = "reason"
    _SNAPSHOT_REASON_DEPTH = "depth_exceeded"
    _SNAPSHOT_REASON_ERROR = "snapshot_failed"

    def __init__(
        self,
        history_tracker: IToolCallHistoryTracker | None = None,
        session_alias_ttl_seconds: int = 3600,
        max_session_aliases: int = 10000,
    ) -> None:
        """Initialize the tool call reactor service.

        Args:
            history_tracker: Optional history tracker for tracking tool calls.
            session_alias_ttl_seconds: TTL for session aliases (default: 1 hour)
            max_session_aliases: Maximum number of session aliases to track (default: 10000)
        """
        self._handlers: dict[str, IToolCallHandler] = {}
        self._history_tracker = history_tracker
        self._lock = asyncio.Lock()
        self._sorted_handlers: tuple[IToolCallHandler, ...] | None = None
        # Telemetry counters for tool access control
        self._tool_definitions_filtered_count: int = 0
        self._tool_calls_blocked_count: int = 0
        self._tool_calls_allowed_count: int = 0
        self._tool_argument_repair_stats: dict[str, int] = {
            "success": 0,
            "recovered": 0,
            "failed": 0,
        }
        # Lock for telemetry counters (for cross-thread protection)
        self._telemetry_lock = threading.Lock()
        # Session alias tracking with TTL-based cleanup to prevent memory leaks
        self._session_aliases: dict[str, str] = {}
        self._session_aliases_last_access: dict[str, datetime] = {}
        self._session_alias_ttl_seconds = session_alias_ttl_seconds
        self._max_session_aliases = max_session_aliases

    def _invalidate_sorted_handlers(self) -> None:
        """Invalidate cached handler ordering."""

        self._sorted_handlers = None

    def _get_sorted_handlers(self) -> tuple[IToolCallHandler, ...]:
        """Return handlers sorted by priority, caching the result."""

        if self._sorted_handlers is None:
            self._sorted_handlers = tuple(
                sorted(
                    self._handlers.values(),
                    key=lambda h: h.priority,
                    reverse=True,
                )
            )
        return self._sorted_handlers

    def register_handler_sync(self, handler: IToolCallHandler) -> None:
        """Register a tool call handler synchronously.

        This method is intended for use during application startup and is not
        thread-safe.

        Args:
            handler: The handler to register.

        Raises:
            ToolCallReactorError: If a handler with the same name is already
                registered.
        """
        if handler.name in self._handlers:
            raise ToolCallReactorError(
                f"Handler with name '{handler.name}' is already registered"
            )

        self._handlers[handler.name] = handler
        self._invalidate_sorted_handlers()
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Registered tool call handler synchronously: {handler.name}")

    async def register_handler(self, handler: IToolCallHandler) -> None:
        """Register a tool call handler.

        Args:
            handler: The handler to register.

        Raises:
            ToolCallReactorError: If a handler with the same name is already registered.
        """
        async with self._lock:
            if handler.name in self._handlers:
                raise ToolCallReactorError(
                    f"Handler with name '{handler.name}' is already registered"
                )

            self._handlers[handler.name] = handler
            self._invalidate_sorted_handlers()
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Registered tool call handler: {handler.name}")

    async def unregister_handler(self, handler_name: str) -> None:
        """Unregister a tool call handler.

        Args:
            handler_name: The name of the handler to unregister.

        Raises:
            ToolCallReactorError: If the handler is not registered.
        """
        async with self._lock:
            if handler_name not in self._handlers:
                raise ToolCallReactorError(
                    f"Handler with name '{handler_name}' is not registered"
                )

            del self._handlers[handler_name]
            self._invalidate_sorted_handlers()
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"Unregistered tool call handler: {handler_name}")

    async def process_tool_call(
        self, context: ToolCallContext
    ) -> ToolCallReactionResult | None:
        """Process a tool call through all registered handlers.

        Args:
            context: The tool call context.

        Returns:
            The reaction result from the first handler that swallows the call,
            or None if no handler swallows it.
        """
        raw_session_id = context.session_id

        if raw_session_id:
            # If session ID is provided, use it directly (or alias it if needed)
            alias_key = raw_session_id
            async with self._lock:
                # Cleanup expired session aliases periodically (before adding new entry)
                await self._cleanup_expired_session_aliases_locked()

                if alias_key not in self._session_aliases:
                    self._session_aliases[alias_key] = str(raw_session_id)
                self._session_aliases_last_access[alias_key] = datetime.now(
                    timezone.utc
                )
                resolved_session_id = self._session_aliases[alias_key]

                # Cleanup again after adding to ensure we don't exceed max limit
                await self._cleanup_expired_session_aliases_locked()
        else:
            # If no session ID, generate a unique one for this specific call context
            # This prevents history mixing between unrelated session-less calls
            resolved_session_id = uuid4().hex

        # Record the tool call in history if tracker is available
        if self._history_tracker:
            timestamp_value = context.timestamp

            if isinstance(timestamp_value, datetime):
                timestamp = (
                    timestamp_value
                    if timestamp_value.tzinfo is not None
                    else timestamp_value.replace(tzinfo=timezone.utc)
                )
            else:
                timestamp = datetime.now(timezone.utc)

            history_context = {
                "backend_name": context.backend_name,
                "model_name": context.model_name,
                "calling_agent": context.calling_agent,
                "timestamp": timestamp,
                "tool_arguments": self._snapshot_tool_arguments(context.tool_arguments),
            }

            await self._history_tracker.record_tool_call(
                resolved_session_id,
                context.tool_name,
                history_context,
            )

        # Get handlers sorted by priority (highest first)
        handlers = self._get_sorted_handlers()

        # Process through handlers
        for handler in handlers:
            try:
                if await handler.can_handle(context):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Handler '{handler.name}' can handle tool call '{context.tool_name}'"
                        )

                    result = await handler.handle(context)

                    if result.should_swallow:
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                f"Handler '{handler.name}' swallowed tool call '{context.tool_name}' "
                                f"in session {resolved_session_id}"
                            )
                        return result

            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Error processing tool call with handler '{handler.name}': {e}",
                        exc_info=True,
                    )
                # Continue with next handler on error

        # No handler swallowed the call
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"No handler swallowed tool call '{context.tool_name}' in session {resolved_session_id}"
            )
        return None

    def get_registered_handlers(self) -> list[str]:
        """Get the names of all registered handlers.

        Returns:
            List of handler names.
        """
        return list(self._handlers.keys())

    def increment_tool_definitions_filtered(self, count: int = 1) -> None:
        """Increment counter for filtered tool definitions.

        Args:
            count: Number of tool definitions filtered (default 1).
        """
        with self._telemetry_lock:
            self._tool_definitions_filtered_count += count

    def increment_tool_calls_blocked(self, count: int = 1) -> None:
        """Increment counter for blocked tool calls.

        Args:
            count: Number of tool calls blocked (default 1).
        """
        with self._telemetry_lock:
            self._tool_calls_blocked_count += count

    def increment_tool_calls_allowed(self, count: int = 1) -> None:
        """Increment counter for allowed tool calls.

        Args:
            count: Number of tool calls allowed (default 1).
        """
        with self._telemetry_lock:
            self._tool_calls_allowed_count += count

    def record_tool_argument_repair_outcome(self, outcome: str) -> None:
        """Record telemetry for tool argument repair attempts."""
        if outcome not in self._tool_argument_repair_stats:
            return
        with self._telemetry_lock:
            self._tool_argument_repair_stats[outcome] += 1

    def get_tool_argument_repair_stats(self) -> dict[str, int]:
        """Return a snapshot of tool argument repair telemetry counters."""
        with self._telemetry_lock:
            return dict(self._tool_argument_repair_stats)

    def get_telemetry_stats(self) -> dict[str, int]:
        """Get telemetry statistics for tool access control.

        Returns:
            Dictionary containing telemetry counters.
        """
        with self._telemetry_lock:
            return {
                "tool_definitions_filtered": self._tool_definitions_filtered_count,
                "tool_calls_blocked": self._tool_calls_blocked_count,
                "tool_calls_allowed": self._tool_calls_allowed_count,
            }

    @classmethod
    def _snapshot_tool_arguments(cls, arguments: Any) -> Any:
        """Create a bounded snapshot of tool arguments for history tracking.

        This method handles both size-based truncation and recursion error protection
        to prevent security handlers from being bypassed by problematic payloads.

        PERFORMANCE OPTIMIZATION: Avoids expensive deepcopy operations by using
        early size-based checks and safer JSON serialization for most cases.
        """
        if arguments is None:
            return None

        # FAST PATH: Handle simple, safe types without any copying
        if isinstance(arguments, int | float | bool | str):
            if isinstance(arguments, str):
                encoded = arguments.encode("utf-8", errors="ignore")
                if len(encoded) <= cls._MAX_ARGUMENT_SNAPSHOT_BYTES:
                    return arguments
                # Truncate string early without copying
                truncated = encoded[: cls._MAX_ARGUMENT_SNAPSHOT_BYTES]
                return {
                    "__truncated__": True,
                    "preview": truncated.decode("utf-8", errors="ignore"),
                    "omitted_bytes": len(encoded) - len(truncated),
                }
            return arguments

        if isinstance(arguments, bytes | bytearray):
            buffer = bytes(arguments)
            if len(buffer) <= cls._MAX_ARGUMENT_SNAPSHOT_BYTES:
                return buffer.decode("utf-8", errors="ignore")
            # Truncate bytes early without copying
            truncated = buffer[: cls._MAX_ARGUMENT_SNAPSHOT_BYTES]
            return {
                "__truncated__": True,
                "preview": truncated.decode("utf-8", errors="ignore"),
                "omitted_bytes": len(buffer) - len(truncated),
            }

        # MEDIUM PATH: Try JSON serialization first (faster than deepcopy for most data)
        try:
            # Use standard JSON serialization for consistency with original behavior
            serialized = json.dumps(arguments, ensure_ascii=False)
            encoded = serialized.encode("utf-8", errors="ignore")

            if len(encoded) <= cls._MAX_ARGUMENT_SNAPSHOT_BYTES:
                # Parse back to get a safe copy without deep recursion
                try:
                    return json.loads(serialized)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # If parsing fails, return the serialized string
                    return serialized
            else:
                # Truncate the JSON string early
                truncated = encoded[: cls._MAX_ARGUMENT_SNAPSHOT_BYTES]
                return {
                    "__truncated__": True,
                    "preview": truncated.decode("utf-8", errors="ignore"),
                    "omitted_bytes": len(encoded) - len(truncated),
                }
        except (TypeError, ValueError, RecursionError):
            # JSON serialization failed, could be due to non-serializable objects or recursion
            pass

        # If the structure is already too deep, avoid deepcopy to prevent stack overflow
        if cls._detect_excessive_depth(arguments):
            return {
                cls._SNAPSHOT_WARNING_KEY: cls._SNAPSHOT_WARNING_VALUE,
                cls._SNAPSHOT_REASON_KEY: cls._SNAPSHOT_REASON_DEPTH,
            }

        # SLOW PATH: Fall back to deepcopy only when absolutely necessary
        # This path is only taken for complex objects that can't be JSON serialized
        try:
            deep_copied = copy.deepcopy(arguments)
        except RecursionError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Tool call arguments exceeded maximum recursion depth; storing"
                    " placeholder instead of raising."
                )
            return {
                cls._SNAPSHOT_WARNING_KEY: cls._SNAPSHOT_WARNING_VALUE,
                cls._SNAPSHOT_REASON_KEY: cls._SNAPSHOT_REASON_DEPTH,
            }
        except Exception as exc:  # pragma: no cover - defensive fallback
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to snapshot tool call arguments (%s); storing fallback"
                    " placeholder instead of raising.",
                    type(exc).__name__,
                    exc_info=True,
                )
            return {
                cls._SNAPSHOT_WARNING_KEY: cls._SNAPSHOT_WARNING_VALUE,
                cls._SNAPSHOT_REASON_KEY: cls._SNAPSHOT_REASON_ERROR,
            }

        # Handle the deep copied data with size limits
        try:
            serialized = json.dumps(deep_copied, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = repr(deep_copied)

        encoded = serialized.encode("utf-8", errors="ignore")
        if len(encoded) > cls._MAX_ARGUMENT_SNAPSHOT_BYTES:
            truncated = encoded[: cls._MAX_ARGUMENT_SNAPSHOT_BYTES]
            return {
                "__truncated__": True,
                "preview": truncated.decode("utf-8", errors="ignore"),
                "omitted_bytes": len(encoded) - len(truncated),
            }

        # If we get here, the arguments are safe and within size limits
        return deep_copied

    async def _cleanup_expired_session_aliases_locked(self) -> None:
        """Remove expired session aliases to prevent unbounded memory growth.

        Must be called while holding self._lock.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self._session_alias_ttl_seconds)

        # Find and remove expired session aliases
        expired = [
            alias_key
            for alias_key, last_access in self._session_aliases_last_access.items()
            if last_access < cutoff
        ]
        for alias_key in expired:
            self._session_aliases.pop(alias_key, None)
            self._session_aliases_last_access.pop(alias_key, None)

        # Enforce max session aliases limit (remove oldest first)
        if len(self._session_aliases) > self._max_session_aliases:
            sorted_aliases = sorted(
                self._session_aliases_last_access.items(),
                key=lambda x: x[1],
            )
            to_remove = len(self._session_aliases) - self._max_session_aliases
            for alias_key, _ in sorted_aliases[:to_remove]:
                self._session_aliases.pop(alias_key, None)
                self._session_aliases_last_access.pop(alias_key, None)

    @classmethod
    def _detect_excessive_depth(cls, value: Any, limit: int = 512) -> bool:
        """Iteratively detect whether a structure exceeds the safe depth limit."""
        stack: list[tuple[Any, int]] = [(value, 0)]
        seen: set[int] = set()

        while stack:
            current, depth = stack.pop()
            if depth > limit:
                return True

            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)

            if isinstance(current, dict):
                stack.extend((v, depth + 1) for v in current.values())
            elif isinstance(current, list | tuple | set):
                stack.extend((item, depth + 1) for item in current)
            else:
                attrs = getattr(current, "__dict__", None)
                if attrs and isinstance(attrs, dict):
                    stack.extend((v, depth + 1) for v in attrs.values())

        return False


class InMemoryToolCallHistoryTracker(IToolCallHistoryTracker):
    """In-memory implementation of tool call history tracking.

    Implements TTL-based cleanup to prevent unbounded memory growth from
    accumulated tool call history across sessions.
    """

    def __init__(
        self,
        session_ttl_seconds: int = 3600,
        max_sessions: int = 10000,
        max_entries_per_session: int = 100,  # Reduced from 1000 to prevent memory bloat
        time_source: Any = None,
    ) -> None:
        """Initialize the history tracker.

        Args:
            session_ttl_seconds: TTL for session history (default: 1 hour)
            max_sessions: Maximum number of sessions to track (default: 10000)
            max_entries_per_session: Maximum tool call entries per session (default: 100)
            time_source: Optional time source for deterministic timestamps (for tests)
        """
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._session_last_access: dict[str, datetime] = {}
        self._session_ttl_seconds = session_ttl_seconds
        self._max_sessions = max_sessions
        self._max_entries_per_session = max_entries_per_session
        self._time_source = time_source
        self._lock = asyncio.Lock()
        # Track total entries across all sessions for global limit enforcement
        self._total_entries = 0

    def _get_now_utc(self) -> datetime:
        """Get current UTC time, respecting time source override if active."""
        if self._time_source is not None:
            return self._time_source.now_utc()
        # Check for time source override (used by tests)
        from src.core.services.time_source_service import _OVERRIDE_TIME_SOURCE

        override = _OVERRIDE_TIME_SOURCE.get()
        if override is not None:
            return override.now_utc()
        return datetime.now(timezone.utc)

    async def record_tool_call(
        self, session_id: str, tool_name: str, context: dict[str, Any]
    ) -> None:
        """Record a tool call in the history.

        Args:
            session_id: The session ID.
            tool_name: The name of the tool called.
            context: Additional context about the call.
        """
        normalized_context = dict(context)

        timestamp_value = normalized_context.get("timestamp")

        if isinstance(timestamp_value, datetime):
            normalized_timestamp = (
                timestamp_value
                if timestamp_value.tzinfo is not None
                else timestamp_value.replace(tzinfo=timezone.utc)
            )
        else:
            normalized_timestamp = self._get_now_utc()

        normalized_context["timestamp"] = normalized_timestamp

        async with self._lock:
            # Cleanup expired sessions periodically
            await self._cleanup_expired_sessions_locked()

            session_history = self._history.setdefault(session_id, [])
            self._session_last_access[session_id] = self._get_now_utc()

            entry = {
                "tool_name": tool_name,
                "timestamp": normalized_timestamp,
                "context": normalized_context,
            }

            session_history.append(entry)
            self._total_entries += 1

            # Enforce per-session limit to prevent memory bloat
            if len(session_history) > self._max_entries_per_session:
                # Remove oldest entries to stay within limit
                excess_count = len(session_history) - self._max_entries_per_session
                self._history[session_id] = session_history[
                    self._max_entries_per_session :
                ]
                self._total_entries -= excess_count

    async def get_call_count(
        self, session_id: str, tool_name: str, time_window_seconds: int
    ) -> int:
        """Get the number of times a tool was called in a time window.

        Args:
            session_id: The session ID.
            tool_name: The name of the tool.
            time_window_seconds: The time window in seconds.

        Returns:
            The number of calls within the time window.
        """
        async with self._lock:
            if session_id not in self._history:
                return 0

            current_time = self._get_now_utc()
            cutoff_time = current_time - timedelta(seconds=time_window_seconds)

            count = 0
            for entry in self._history[session_id]:
                if entry["tool_name"] != tool_name:
                    continue

                entry_timestamp = entry.get("timestamp")

                if not isinstance(entry_timestamp, datetime):
                    continue

                timestamp = (
                    entry_timestamp
                    if entry_timestamp.tzinfo is not None
                    else entry_timestamp.replace(tzinfo=timezone.utc)
                )

                if timestamp >= cutoff_time:
                    count += 1

            return count

    async def _cleanup_expired_sessions_locked(self) -> None:
        """Remove expired session histories to prevent cross-session data leaks.

        Must be called while holding self._lock.
        """
        now = self._get_now_utc()
        cutoff = now - timedelta(seconds=self._session_ttl_seconds)

        # Find and remove expired sessions
        expired = [
            session_id
            for session_id, last_access in self._session_last_access.items()
            if last_access < cutoff
        ]
        for session_id in expired:
            self._history.pop(session_id, None)
            self._session_last_access.pop(session_id, None)

        # Enforce max sessions limit (remove oldest first)
        if len(self._history) > self._max_sessions:
            sorted_sessions = sorted(
                self._session_last_access.items(),
                key=lambda x: x[1],
            )
            to_remove = len(self._history) - self._max_sessions
            for session_id, _ in sorted_sessions[:to_remove]:
                # Subtract entries being removed from total count
                session_history = self._history.get(session_id, [])
                self._total_entries -= len(session_history)
                # Remove session from history and last access tracking
                self._history.pop(session_id, None)
                self._session_last_access.pop(session_id, None)

    async def get_total_entries_count(self) -> int:
        """Get the total number of tool call entries across all sessions.

        Returns:
            Total number of entries stored in memory.
        """
        async with self._lock:
            return self._total_entries

    async def clear_history(self, session_id: str | None = None) -> None:
        """Clear the call history.

        Args:
            session_id: Optional session ID to clear history for.
                       If None, clears all history.
        """
        async with self._lock:
            if session_id is None:
                # Reset total count when clearing all history
                self._total_entries = 0
                self._history.clear()
                self._session_last_access.clear()
            elif session_id in self._history:
                # Subtract entries being removed from total count
                session_history = self._history.get(session_id, [])
                self._total_entries -= len(session_history)
                self._history[session_id].clear()
                self._session_last_access.pop(session_id, None)


import sys

# Allow tests to construct deeply nested objects without immediate RecursionError.
if sys.getrecursionlimit() < 5000:  # pragma: no cover - defensive configuration
    sys.setrecursionlimit(5000)
