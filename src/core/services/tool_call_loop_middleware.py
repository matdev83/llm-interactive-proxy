"""
Tool call loop detection middleware for the response pipeline.

This middleware detects repetitive tool call patterns and intervenes to prevent
models from getting stuck in a loop.
"""

from __future__ import annotations

# type: ignore[unreachable]
import json
import logging
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from cachetools import TTLCache

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
)
from src.core.services.streaming.stream_context_registry import (
    ToolCallBufferState,
    get_global_streaming_context_registry,
)
from src.core.utils.message_processing_utils import is_message_processed
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
    build_tool_call_signature,
)
from src.tool_call_loop.tracker import ToolCallTracker

if TYPE_CHECKING:
    from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

logger = logging.getLogger(__name__)


class ToolCallLoopDetectionFeature(IResponseFeature):
    """Feature to detect tool call loops with enforced streaming/non-streaming parity.

    This feature tracks tool calls in responses and detects repetitive patterns
    that may indicate a model is stuck in a loop.
    """

    def __init__(
        self,
        max_cached_sessions: int = 256,
        lifecycle_registry: ToolCallLifecycleRegistry | None = None,
        priority: int = 0,
    ) -> None:
        """Initialize the feature."""
        super().__init__(priority)
        if max_cached_sessions <= 0:
            raise ValueError("max_cached_sessions must be positive")

        self._session_trackers: MutableMapping[str, ToolCallTracker] = TTLCache(
            maxsize=max_cached_sessions, ttl=3600
        )
        self._max_cached_sessions = max_cached_sessions
        self._lifecycle = lifecycle_registry or ToolCallLifecycleRegistry()
        # Keep track of background tasks to prevent GC
        self._background_tasks: set[Any] = set()

    async def _process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool,
    ) -> Any:
        """Shared processing logic for both streaming and non-streaming."""
        if not context:
            return response

        config = context.get("config")
        if not config or not isinstance(config, LoopDetectionConfiguration):
            return response

        if not config.tool_loop_detection_enabled:
            return response

        metadata = getattr(response, "metadata", {}) or {}

        buffer_state = self._resolve_buffer_state(context)
        if buffer_state is not None:
            tool_calls = self._consume_buffered_calls(buffer_state)
            if not tool_calls:
                return response
            new_tool_calls = tool_calls
        else:
            tool_calls = self._extract_tool_calls(response.content)
            if not tool_calls:
                tool_calls = self._extract_tool_calls_from_metadata(metadata)
            if not tool_calls:
                return response

            new_tool_calls = self._filter_new_tool_calls(tool_calls, response)
            if not new_tool_calls:
                logger.log(
                    5,
                    "Skipping loop detection - all %d tool calls already processed",
                    len(tool_calls),
                )
                return response

        tracker_config = self._build_tracker_config(config)

        resolved_session_id = (
            context.get("stream_id")
            or session_id
            or context.get("_tool_call_loop_session_id")
        )
        if not resolved_session_id:
            resolved_session_id = context.setdefault(
                "_tool_call_loop_session_id", uuid4().hex
            )
        else:
            resolved_session_id = str(resolved_session_id)
            context.setdefault("_tool_call_loop_session_id", resolved_session_id)

        # Both streaming and non-streaming: clear lifecycle for fresh detection
        # This ensures parity - each response/chunk is evaluated independently
        if not is_streaming:
            await self._lifecycle.clear_stream(resolved_session_id)

        tracker = self._session_trackers.get(resolved_session_id)
        if tracker is None:
            tracker = ToolCallTracker(config=tracker_config)
            self._session_trackers[resolved_session_id] = tracker
            self._enforce_cache_limit()
        else:
            # TTLCache automatically updates access time on get(), so no need for move_to_end
            # Refresh the item in cache to update its TTL
            self._session_trackers[resolved_session_id] = tracker
            if tracker.config != tracker_config:
                tracker.config = tracker_config

        for tool_call in new_tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")

            signature = build_tool_call_signature(tool_call)
            if not await self._lifecycle.register_detection(
                resolved_session_id, signature
            ):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping duplicate in-flight tool call (signature=%s) "
                        "for stream %s",
                        signature,
                        resolved_session_id,
                    )
                continue

            tracking_result = tracker.track_tool_call(tool_name, arguments)

            if tracking_result.should_block:
                logger.warning(
                    "Tool call loop detected in session %s: tool=%s, repeats=%s/%s, "
                    "window=%ss, mode=%s",
                    resolved_session_id,
                    tool_name,
                    tracking_result.repeat_count,
                    tracker.config.max_repeats,
                    tracker.config.ttl_seconds,
                    tracker.config.mode.value,
                )

                raise ToolCallLoopError(
                    message=f"Tool call loop detected: {tracking_result.reason}",
                    details={
                        "tool_name": tool_name,
                        "repetitions": tracking_result.repeat_count,
                        "mode": tracker.config.mode.value,
                    },
                )

            if buffer_state is None:
                tool_call["_already_processed"] = True
            await self._lifecycle.mark_processed(resolved_session_id, signature)

        if buffer_state is None:
            self._mark_message_processed(response)

        return response

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process non-streaming response for tool call loops."""
        return await self._process_response(
            response, session_id, context, is_streaming=False
        )

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process streaming chunk for tool call loops."""
        return await self._process_response(
            chunk, session_id, context, is_streaming=True
        )

    def reset_session(self, session_id: str) -> None:
        """Reset the tracker for a session."""
        if session_id in self._session_trackers:
            del self._session_trackers[session_id]
        if self._lifecycle is not None:
            # clear_stream is async but we're in a sync method
            # Schedule it as a fire-and-forget task if event loop is available
            import asyncio

            try:
                # We don't use the loop variable, just check it exists
                asyncio.get_running_loop()
                # Fire and forget - don't await, but store reference to avoid GC
                task = asyncio.create_task(self._lifecycle.clear_stream(session_id))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                # No event loop available, skip async cleanup
                pass

    def _extract_tool_calls(self, content: Any) -> list[dict[str, Any]]:
        """Extract tool calls from response content."""
        if isinstance(content, dict):
            data = content
        else:
            if isinstance(content, str | bytes | bytearray):
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    return []
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Unsupported response content type for tool call "
                        "extraction: %s",
                        type(content).__name__,
                    )
                return []

        if isinstance(data, dict):
            choices = data.get("choices", [])
            for choice in choices:
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])
                if (
                    tool_calls
                    and isinstance(tool_calls, list)
                    and all(isinstance(item, dict) for item in tool_calls)
                ):
                    result: list[dict[str, Any]] = []
                    for item in tool_calls:
                        if isinstance(item, dict):
                            result.append(item)
                    return result

        if isinstance(data, list) and all(
            isinstance(item, dict) and "function" in item for item in data
        ):
            return data

        return []

    def _extract_tool_calls_from_metadata(self, metadata: Any) -> list[dict[str, Any]]:
        """Extract tool calls from metadata."""
        if not metadata or not isinstance(metadata, dict):
            return []

        tool_calls = metadata.get("tool_calls")
        if (
            isinstance(tool_calls, list)
            and tool_calls
            and all(isinstance(item, dict) for item in tool_calls)
        ):
            return list(tool_calls)

        return []

    def _enforce_cache_limit(self) -> None:
        """Ensure the session tracker cache does not grow without bound."""
        while len(self._session_trackers) > self._max_cached_sessions:
            # TTLCache.popitem() removes the least recently used item (oldest)
            evicted_session_id, _ = self._session_trackers.popitem()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicted tool call tracker for session %s due to cache limit",
                    evicted_session_id,
                )

    def _build_tracker_config(
        self, config: LoopDetectionConfiguration
    ) -> ToolCallLoopConfig:
        """Build tracker config from loop detection configuration."""
        from src.tool_call_loop.config import ToolCallLoopConfig

        return ToolCallLoopConfig(
            enabled=config.tool_loop_detection_enabled,
            max_repeats=config.tool_loop_max_repeats or 4,
            ttl_seconds=config.tool_loop_ttl_seconds or 120,
            mode=self._resolve_tool_loop_mode(config.tool_loop_mode),
        )

    def _resolve_tool_loop_mode(
        self, mode_value: ToolLoopMode | str | None
    ) -> ToolLoopMode:
        """Resolve tool loop mode from various input types."""
        from src.tool_call_loop.config import ToolLoopMode

        if isinstance(mode_value, ToolLoopMode):
            return mode_value

        if isinstance(mode_value, str):
            normalized = mode_value.strip().lower()
            if normalized == "chance":
                normalized = "chance_then_break"
            try:
                return ToolLoopMode(normalized)
            except ValueError:
                logger.warning(
                    "Invalid tool loop mode '%s' provided; falling back to break mode.",
                    mode_value,
                )

        return ToolLoopMode.BREAK

    def _filter_new_tool_calls(
        self, tool_calls: list[dict[str, Any]], response: Any
    ) -> list[dict[str, Any]]:
        """Filter tool calls to only include new ones."""
        if hasattr(response, "content") and isinstance(response.content, dict):
            choices = response.content.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                if is_message_processed(message):
                    return []

        new_tool_calls = [
            tc for tc in tool_calls if not tc.get("_already_processed", False)
        ]

        return new_tool_calls

    def _resolve_buffer_state(
        self, context: dict[str, Any] | None
    ) -> ToolCallBufferState | None:
        if not context:
            return None
        candidate = context.get("tool_call_buffer_state")
        if isinstance(candidate, ToolCallBufferState):
            return candidate

        stream_identifier = context.get("stream_id") or context.get("session_id")
        if not stream_identifier:
            return None

        registry = get_global_streaming_context_registry()
        try:
            return registry.get_tool_call_buffer(str(stream_identifier))
        except (AttributeError, KeyError, TypeError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to get tool call buffer for stream %s",
                    stream_identifier,
                    exc_info=True,
                )
            return None

    @staticmethod
    def _consume_buffered_calls(
        buffer_state: ToolCallBufferState,
    ) -> list[dict[str, Any]]:
        """Consume buffered calls from buffer state."""
        if not buffer_state.detected_calls:
            return []
        if buffer_state.loop_cursor >= len(buffer_state.detected_calls):
            return []
        new_calls = buffer_state.detected_calls[buffer_state.loop_cursor :]
        buffer_state.loop_cursor = len(buffer_state.detected_calls)
        return new_calls

    @staticmethod
    def _mark_message_processed(response: Any) -> None:
        """Mark message payloads so downstream middleware skips already-checked calls."""
        if not hasattr(response, "content"):
            return
        if not isinstance(response.content, dict):
            try:
                if isinstance(response.content, str):
                    payload = json.loads(response.content)
                else:
                    return
            except (TypeError, ValueError, json.JSONDecodeError):
                return
        else:
            payload = response.content

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        message = choices[0].get("message")
        if isinstance(message, dict):
            message["_tool_calls_processed"] = True


# Legacy middleware kept for backward compatibility during transition
# DEPRECATED: Use ToolCallLoopDetectionFeature instead
class ToolCallLoopDetectionMiddleware(IResponseMiddleware):
    """DEPRECATED: Use ToolCallLoopDetectionFeature instead.

    Legacy middleware to detect and prevent tool call loops.
    This class is kept for backward compatibility only.
    """

    def __init__(
        self,
        max_cached_sessions: int = 256,
        lifecycle_registry: ToolCallLifecycleRegistry | None = None,
    ) -> None:
        """Initialize the middleware."""
        logger.error(
            "DEPRECATED: ToolCallLoopDetectionMiddleware instantiated. "
            "Use ToolCallLoopDetectionFeature instead for proper streaming/non-streaming parity."
        )
        if max_cached_sessions <= 0:
            raise ValueError("max_cached_sessions must be positive")

        self._session_trackers: MutableMapping[str, ToolCallTracker] = TTLCache(
            maxsize=max_cached_sessions, ttl=3600
        )
        self._max_cached_sessions = max_cached_sessions
        self._lifecycle = lifecycle_registry or ToolCallLifecycleRegistry()
        # Keep track of background tasks to prevent GC
        self._background_tasks: set[Any] = set()

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response and check for tool call loops.

        Args:
            response: The processed response
            session_id: The ID of the session
            context: Additional context

        Returns:
            The processed response or an error response if loops detected

        Raises:
            ToolCallLoopError: If a tool call loop is detected
        """
        # Skip processing if no context
        if not context:
            return response

        # Get config from context
        config = context.get("config")
        if not config or not isinstance(config, LoopDetectionConfiguration):
            return response

        # Skip if tool loop detection is disabled
        if not config.tool_loop_detection_enabled:
            return response

        metadata = getattr(response, "metadata", {}) or {}

        buffer_state = self._resolve_buffer_state(context)
        if buffer_state is not None:
            tool_calls = self._consume_buffered_calls(buffer_state)
            if not tool_calls:
                return response
            new_tool_calls = tool_calls
        else:
            # Extract tool calls from response content or metadata
            tool_calls = self._extract_tool_calls(response.content)
            if not tool_calls:
                tool_calls = self._extract_tool_calls_from_metadata(metadata)
            if not tool_calls:
                return response

            # Filter out already-processed tool calls to avoid tracking historical data
            new_tool_calls = self._filter_new_tool_calls(tool_calls, response)
            if not new_tool_calls:
                logger.log(
                    5,  # TRACE level
                    f"Skipping loop detection - all {len(tool_calls)} tool calls already processed",
                )
                return response

        tracker_config = self._build_tracker_config(config)

        resolved_session_id = (
            context.get("stream_id")
            or session_id
            or context.get("_tool_call_loop_session_id")
        )
        if not resolved_session_id:
            resolved_session_id = context.setdefault(
                "_tool_call_loop_session_id", uuid4().hex
            )
        else:
            resolved_session_id = str(resolved_session_id)
            context.setdefault("_tool_call_loop_session_id", resolved_session_id)

        # Non-streaming responses should treat each detection pass independently
        if not is_streaming:
            await self._lifecycle.clear_stream(resolved_session_id)

        tracker = self._session_trackers.get(resolved_session_id)
        if tracker is None:
            tracker = ToolCallTracker(config=tracker_config)
            self._session_trackers[resolved_session_id] = tracker
            self._enforce_cache_limit()
        else:
            # TTLCache automatically updates access time on get(), so no need for move_to_end
            # Refresh the item in cache to update its TTL
            self._session_trackers[resolved_session_id] = tracker
            if tracker.config != tracker_config:
                tracker.config = tracker_config

        # Process each NEW tool call only
        for tool_call in new_tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")

            signature = build_tool_call_signature(tool_call)
            if not await self._lifecycle.register_detection(
                resolved_session_id, signature
            ):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping duplicate in-flight tool call (signature=%s) for stream %s",
                        signature,
                        resolved_session_id,
                    )
                continue

            # Track the tool call
            tracking_result = tracker.track_tool_call(tool_name, arguments)

            if tracking_result.should_block:
                logger.warning(
                    f"Tool call loop detected in session {resolved_session_id}: "
                    f"tool={tool_name}, repeats={tracking_result.repeat_count}/{tracker.config.max_repeats}, "
                    f"window={tracker.config.ttl_seconds}s, "
                    f"mode={tracker.config.mode.value}"
                )

                # Raise an error to stop the response
                raise ToolCallLoopError(
                    message=f"Tool call loop detected: {tracking_result.reason}",
                    details={
                        "tool_name": tool_name,
                        "repetitions": tracking_result.repeat_count,
                        "mode": tracker.config.mode.value,
                    },
                )

            if buffer_state is None:
                tool_call["_already_processed"] = True
            await self._lifecycle.mark_processed(resolved_session_id, signature)

        if buffer_state is None:
            self._mark_message_processed(response)

        # If we get here, no loops were detected
        return response

    def reset_session(self, session_id: str) -> None:
        """Reset the tracker for a session.

        Args:
            session_id: The ID of the session to reset
        """
        if session_id in self._session_trackers:
            del self._session_trackers[session_id]
        if self._lifecycle is not None:
            # clear_stream is async but we're in a sync method
            # Schedule it as a fire-and-forget task if event loop is available
            import asyncio

            try:
                # We don't use the loop variable, just check it exists
                asyncio.get_running_loop()
                # Fire and forget - don't await, but store reference to avoid GC
                task = asyncio.create_task(self._lifecycle.clear_stream(session_id))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                # No event loop available, skip async cleanup
                pass

    def _extract_tool_calls(self, content: Any) -> list[dict[str, Any]]:
        """Extract tool calls from response content.

        Args:
            content: The response content (can be a string or a dict)

        Returns:
            List of tool call dictionaries
        """
        # If content is already a dict, use it directly
        if isinstance(content, dict):
            data = content
        else:
            # Otherwise try to parse common JSON container types
            if isinstance(content, str | bytes | bytearray):
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Not JSON or doesn't have the expected structure
                    return []
            else:
                # Unsupported content type (e.g., streaming iterators)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Unsupported response content type for tool call extraction: %s",
                        type(content).__name__,
                    )
                return []

        # Check for OpenAI format
        if isinstance(data, dict):
            choices = data.get("choices", [])
            for choice in choices:
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])
                if (
                    tool_calls
                    and isinstance(tool_calls, list)
                    and all(isinstance(item, dict) for item in tool_calls)
                ):
                    # Create a new list with explicit typing
                    result: list[dict[str, Any]] = []
                    for item in tool_calls:
                        if isinstance(item, dict):
                            result.append(item)
                    return result

        # Check for direct tool calls array
        if isinstance(data, list) and all(  # type: ignore[unreachable]
            isinstance(item, dict) and "function" in item for item in data
        ):  # type: ignore[unreachable]
            return data  # type: ignore[unreachable]

        return []

    def _extract_tool_calls_from_metadata(self, metadata: Any) -> list[dict[str, Any]]:
        if not metadata or not isinstance(metadata, dict):
            return []

        tool_calls = metadata.get("tool_calls")
        if (
            isinstance(tool_calls, list)
            and tool_calls
            and all(isinstance(item, dict) for item in tool_calls)
        ):
            return list(tool_calls)

        return []

    def _enforce_cache_limit(self) -> None:
        """Ensure the session tracker cache does not grow without bound."""
        while len(self._session_trackers) > self._max_cached_sessions:
            # TTLCache.popitem() removes the least recently used item (oldest)
            evicted_session_id, _ = self._session_trackers.popitem()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicted tool call tracker for session %s due to cache limit",
                    evicted_session_id,
                )

    def _build_tracker_config(
        self, config: LoopDetectionConfiguration
    ) -> ToolCallLoopConfig:
        from src.tool_call_loop.config import ToolCallLoopConfig

        return ToolCallLoopConfig(
            enabled=config.tool_loop_detection_enabled,
            max_repeats=config.tool_loop_max_repeats or 4,
            ttl_seconds=config.tool_loop_ttl_seconds or 120,
            mode=self._resolve_tool_loop_mode(config.tool_loop_mode),
        )

    def _resolve_tool_loop_mode(
        self, mode_value: ToolLoopMode | str | None
    ) -> ToolLoopMode:
        from src.tool_call_loop.config import ToolLoopMode

        if isinstance(mode_value, ToolLoopMode):
            return mode_value

        if isinstance(mode_value, str):
            normalized = mode_value.strip().lower()
            if normalized == "chance":
                normalized = "chance_then_break"
            try:
                return ToolLoopMode(normalized)
            except ValueError:
                logger.warning(
                    "Invalid tool loop mode '%s' provided; falling back to break mode.",
                    mode_value,
                )

        return ToolLoopMode.BREAK

    def _filter_new_tool_calls(
        self, tool_calls: list[dict[str, Any]], response: Any
    ) -> list[dict[str, Any]]:
        """Filter tool calls to only include new ones that haven't been processed.

        This method implements a hybrid approach:
        1. Check if tool calls have a processing marker (primary)
        2. Check if the response message has been processed (fallback)

        Args:
            tool_calls: List of tool call dictionaries
            response: The response object containing the tool calls

        Returns:
            List of new (unprocessed) tool calls
        """
        # Check if the response itself has been processed
        # This handles the case where the entire message was processed
        if hasattr(response, "content") and isinstance(response.content, dict):
            # Check if this is from a message that was already processed
            choices = response.content.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                if is_message_processed(message):
                    return []

        # Filter individual tool calls that have been marked as processed
        new_tool_calls = [
            tc for tc in tool_calls if not tc.get("_already_processed", False)
        ]

        return new_tool_calls

    def _resolve_buffer_state(
        self, context: dict[str, Any] | None
    ) -> ToolCallBufferState | None:
        if not context:
            return None
        candidate = context.get("tool_call_buffer_state")
        if isinstance(candidate, ToolCallBufferState):
            return candidate

        stream_identifier = context.get("stream_id") or context.get("session_id")
        if not stream_identifier:
            return None

        registry = get_global_streaming_context_registry()
        try:
            return registry.get_tool_call_buffer(str(stream_identifier))
        except (AttributeError, KeyError, TypeError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to get tool call buffer for stream %s",
                    stream_identifier,
                    exc_info=True,
                )
            return None

    @staticmethod
    def _consume_buffered_calls(
        buffer_state: ToolCallBufferState,
    ) -> list[dict[str, Any]]:
        if not buffer_state.detected_calls:
            return []
        if buffer_state.loop_cursor >= len(buffer_state.detected_calls):
            return []
        new_calls = buffer_state.detected_calls[buffer_state.loop_cursor :]
        buffer_state.loop_cursor = len(buffer_state.detected_calls)
        return new_calls

    @staticmethod
    def _mark_message_processed(response: Any) -> None:
        """Mark message payloads so downstream middleware skips already-checked calls."""
        if not hasattr(response, "content"):
            return
        if not isinstance(response.content, dict):
            try:
                if isinstance(response.content, str):
                    payload = json.loads(response.content)
                else:
                    return
            except (TypeError, ValueError, json.JSONDecodeError):
                return
        else:
            payload = response.content

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        message = choices[0].get("message")
        if isinstance(message, dict):
            message["_tool_calls_processed"] = True
