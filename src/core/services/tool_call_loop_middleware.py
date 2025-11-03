"""
Tool call loop detection middleware for the response pipeline.

This middleware detects repetitive tool call patterns and intervenes to prevent
models from getting stuck in a loop.
"""

from __future__ import annotations

# type: ignore[unreachable]
import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.utils.message_processing_utils import (
    is_message_processed,
    mark_message_processed,
)
from src.tool_call_loop.tracker import ToolCallTracker

if TYPE_CHECKING:
    from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

logger = logging.getLogger(__name__)


class ToolCallLoopDetectionMiddleware(IResponseMiddleware):
    """Middleware to detect and prevent tool call loops.

    This middleware tracks tool calls in responses and detects repetitive patterns
    that may indicate a model is stuck in a loop.
    """

    def __init__(self, max_cached_sessions: int = 256) -> None:
        """Initialize the middleware."""
        if max_cached_sessions <= 0:
            raise ValueError("max_cached_sessions must be positive")

        self._session_trackers: OrderedDict[str, ToolCallTracker] = OrderedDict()
        self._max_cached_sessions = max_cached_sessions

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

        resolved_session_id = session_id or context.get("stream_id")
        if not resolved_session_id:
            resolved_session_id = context.setdefault(
                "_tool_call_loop_session_id", uuid4().hex
            )
        else:
            resolved_session_id = str(resolved_session_id)
            context.setdefault("_tool_call_loop_session_id", resolved_session_id)

        tracker = self._session_trackers.get(resolved_session_id)
        if tracker is None:
            tracker = ToolCallTracker(config=tracker_config)
            self._session_trackers[resolved_session_id] = tracker
            self._enforce_cache_limit()
        else:
            self._session_trackers.move_to_end(resolved_session_id)
            if tracker.config != tracker_config:
                tracker.config = tracker_config

        # Process each NEW tool call only
        for tool_call in new_tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")

            # Track the tool call
            should_block, reason, repeat_count = tracker.track_tool_call(
                tool_name, arguments
            )

            if should_block:
                logger.warning(
                    f"Tool call loop detected in session {resolved_session_id}: "
                    f"tool={tool_name}, repeats={repeat_count}/{tracker.config.max_repeats}, "
                    f"window={tracker.config.ttl_seconds}s, "
                    f"mode={tracker.config.mode.value}"
                )

                # Raise an error to stop the response
                raise ToolCallLoopError(
                    message=f"Tool call loop detected: {reason}",
                    details={
                        "tool_name": tool_name,
                        "repetitions": repeat_count,
                        "mode": tracker.config.mode.value,
                    },
                )

        # Mark tool calls as processed after tracking
        self._mark_tool_calls_processed(tool_calls, response)

        # If we get here, no loops were detected
        return response

    def reset_session(self, session_id: str) -> None:
        """Reset the tracker for a session.

        Args:
            session_id: The ID of the session to reset
        """
        if session_id in self._session_trackers:
            del self._session_trackers[session_id]

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
            evicted_session_id, _ = self._session_trackers.popitem(last=False)
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

    def _mark_tool_calls_processed(
        self, tool_calls: list[dict[str, Any]], response: Any
    ) -> None:
        """Mark tool calls as processed to prevent reprocessing.

        Args:
            tool_calls: List of tool call dictionaries to mark
            response: The response object containing the tool calls
        """
        # Mark individual tool calls as processed
        for tool_call in tool_calls:
            tool_call["_already_processed"] = True

        # Also mark the message as processed if we can access it
        if hasattr(response, "content") and isinstance(response.content, dict):
            choices = response.content.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                mark_message_processed(message)
