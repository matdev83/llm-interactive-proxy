"""
Tool call loop detection middleware for the response pipeline.

This middleware detects repetitive tool call patterns and intervenes to prevent
models from getting stuck in a loop.
"""

from __future__ import annotations

# type: ignore[unreachable]
import json
import logging
from typing import Any

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.tool_call_loop.tracker import ToolCallTracker

logger = logging.getLogger(__name__)


class ToolCallLoopDetectionMiddleware(IResponseMiddleware):
    """Middleware to detect and prevent tool call loops.

    This middleware tracks tool calls in responses and detects repetitive patterns
    that may indicate a model is stuck in a loop.
    """

    def __init__(self) -> None:
        """Initialize the middleware."""
        self._session_trackers: dict[str, ToolCallTracker] = {}

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
        # Skip processing if no context or no content
        if not context or not response.content:
            return response

        # Get config from context
        config = context.get("config")
        if not config or not isinstance(config, LoopDetectionConfiguration):
            return response

        # Skip if tool loop detection is disabled
        if not config.tool_loop_detection_enabled:
            return response

        # Extract tool calls from response content
        tool_calls = self._extract_tool_calls(response.content)
        if not tool_calls:
            return response

        # Initialize tracker for this session if needed
        if session_id not in self._session_trackers:
            from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

            tracker = ToolCallTracker(
                config=ToolCallLoopConfig(
                    enabled=config.tool_loop_detection_enabled,
                    max_repeats=config.tool_loop_max_repeats or 4,
                    ttl_seconds=config.tool_loop_ttl_seconds or 120,
                    mode=(
                        config.tool_loop_mode
                        if isinstance(config.tool_loop_mode, ToolLoopMode)
                        else ToolLoopMode.BREAK
                    ),
                )
            )
            self._session_trackers[session_id] = tracker
        else:
            tracker = self._session_trackers[session_id]

        # Process each tool call
        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")

            # Track the tool call
            should_block, reason, repeat_count = tracker.track_tool_call(
                tool_name, arguments
            )

            if should_block:
                logger.warning(
                    f"Tool call loop detected in session {session_id}: "
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
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Unsupported response content type for tool call extraction: %s",
                        type(content).__name__,
                    )
                return []

        # Check for OpenAI format
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if isinstance(choices, list):
                result: list[dict[str, Any]] = []

                for choice in choices:
                    if not isinstance(choice, dict):
                        continue

                    message = choice.get("message")
                    if isinstance(message, dict):
                        tool_calls = message.get("tool_calls")
                        if isinstance(tool_calls, list):
                            result.extend(
                                item for item in tool_calls if isinstance(item, dict)
                            )

                    # Streaming chunks use the delta field instead of message
                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        tool_calls = delta.get("tool_calls")
                        if isinstance(tool_calls, list):
                            result.extend(
                                item for item in tool_calls if isinstance(item, dict)
                            )

                if result:
                    return result

        # Check for direct tool calls array
        if isinstance(data, list) and all(  # type: ignore[unreachable]
            isinstance(item, dict) and "function" in item for item in data
        ):  # type: ignore[unreachable]
            return data  # type: ignore[unreachable]

        return []
