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

    def __init__(self, history_tracker: IToolCallHistoryTracker | None = None) -> None:
        """Initialize the tool call reactor service.

        Args:
            history_tracker: Optional history tracker for tracking tool calls.
        """
        self._handlers: dict[str, IToolCallHandler] = {}
        self._history_tracker = history_tracker
        self._lock = asyncio.Lock()
        self._session_aliases: dict[str, str] = {}

        # Telemetry counters for tool access control
        self._tool_definitions_filtered_count = 0
        self._tool_calls_blocked_count = 0
        self._tool_calls_allowed_count = 0

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
        alias_key = raw_session_id if raw_session_id else "__empty__"
        if alias_key not in self._session_aliases:
            self._session_aliases[alias_key] = (
                str(raw_session_id) if raw_session_id else uuid4().hex
            )
        resolved_session_id = self._session_aliases[alias_key]

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
        handlers = sorted(
            self._handlers.values(),
            key=lambda h: h.priority,
            reverse=True,
        )

        # Process through handlers
        for handler in handlers:
            try:
                if await handler.can_handle(context):
                    logger.debug(
                        f"Handler '{handler.name}' can handle tool call '{context.tool_name}'"
                    )

                    result = await handler.handle(context)

                    if result.should_swallow:
                        logger.info(
                            f"Handler '{handler.name}' swallowed tool call '{context.tool_name}' "
                            f"in session {resolved_session_id}"
                        )
                        return result

            except Exception as e:
                logger.error(
                    f"Error processing tool call with handler '{handler.name}': {e}",
                    exc_info=True,
                )
                # Continue with next handler on error

        # No handler swallowed the call
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
        """Increment the counter for filtered tool definitions.

        Args:
            count: Number of tool definitions filtered (default 1).
        """
        self._tool_definitions_filtered_count += count

    def increment_tool_calls_blocked(self, count: int = 1) -> None:
        """Increment the counter for blocked tool calls.

        Args:
            count: Number of tool calls blocked (default 1).
        """
        self._tool_calls_blocked_count += count

    def increment_tool_calls_allowed(self, count: int = 1) -> None:
        """Increment the counter for allowed tool calls.

        Args:
            count: Number of tool calls allowed (default 1).
        """
        self._tool_calls_allowed_count += count

    def get_telemetry_stats(self) -> dict[str, int]:
        """Get telemetry statistics for tool access control.

        Returns:
            Dictionary containing telemetry counters.
        """
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
            logger.warning(
                "Tool call arguments exceeded maximum recursion depth; storing"
                " placeholder instead of raising."
            )
            return {
                cls._SNAPSHOT_WARNING_KEY: cls._SNAPSHOT_WARNING_VALUE,
                cls._SNAPSHOT_REASON_KEY: cls._SNAPSHOT_REASON_DEPTH,
            }
        except Exception as exc:  # pragma: no cover - defensive fallback
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
    """In-memory implementation of tool call history tracking."""

    def __init__(self) -> None:
        """Initialize the history tracker."""
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

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
            normalized_timestamp = datetime.now(timezone.utc)

        normalized_context["timestamp"] = normalized_timestamp

        async with self._lock:
            session_history = self._history.setdefault(session_id, [])

            entry = {
                "tool_name": tool_name,
                "timestamp": normalized_timestamp,
                "context": normalized_context,
            }

            session_history.append(entry)

            # Keep only recent entries (last 1000 per session)
            if len(session_history) > 1000:
                self._history[session_id] = session_history[-1000:]

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

            current_time = datetime.now(timezone.utc)
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

    async def clear_history(self, session_id: str | None = None) -> None:
        """Clear the call history.

        Args:
            session_id: Optional session ID to clear history for.
                       If None, clears all history.
        """
        async with self._lock:
            if session_id is None:
                self._history.clear()
            elif session_id in self._history:
                self._history[session_id].clear()


import sys

# Allow tests to construct deeply nested objects without immediate RecursionError.
if sys.getrecursionlimit() < 5000:  # pragma: no cover - defensive configuration
    sys.setrecursionlimit(5000)
