"""
Tool call loop detection middleware for the response pipeline.

This middleware detects repetitive tool call patterns and intervenes to prevent
models from getting stuck in a loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.interfaces.response_processor_interface import (
    ProcessedResponse as ProcessedResult,
)
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
        response: ProcessedResult,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResult:
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

    def _extract_tool_calls(self, content: str) -> list[dict[str, Any]]:
        """Extract tool calls from response content.

        Args:
            content: The response content

        Returns:
            List of tool call dictionaries
        """
        try:
            # Try to parse content as JSON
            data = json.loads(content)

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
            if isinstance(data, list) and all(
                isinstance(item, dict) and "function" in item for item in data
            ):
                return data

        except (json.JSONDecodeError, TypeError, ValueError):
            # Not JSON or doesn't have the expected structure
            pass

        return []
