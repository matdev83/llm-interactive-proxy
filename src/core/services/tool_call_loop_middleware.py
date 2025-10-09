"""
Tool call loop detection middleware for the response pipeline.

This middleware detects repetitive tool call patterns and intervenes to prevent
models from getting stuck in a loop.
"""

from __future__ import annotations

# type: ignore[unreachable]
import json
import logging
from typing import TYPE_CHECKING, Any

from src.core.common.exceptions import ToolCallLoopError
from src.core.domain.configuration.loop_detection_config import (
    LoopDetectionConfiguration,
)
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.tool_call_loop.tracker import ToolCallTracker

if TYPE_CHECKING:
    from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

logger = logging.getLogger(__name__)


class ToolCallLoopDetectionMiddleware(IResponseMiddleware):
    """Middleware to detect and prevent tool call loops.

    This middleware tracks tool calls in responses and detects repetitive patterns
    that may indicate a model is stuck in a loop.
    """

    def __init__(self) -> None:
        """Initialize the middleware."""
        self._session_trackers: dict[str, ToolCallTracker] = {}
        # Maintain partial streaming tool call state per session so we can
        # reconstruct complete tool call payloads when providers send them
        # across multiple streaming chunks.
        self._streaming_tool_state: dict[str, dict[int, dict[str, Any]]] = {}

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
        tool_calls = self._extract_tool_calls(
            response.content, session_id, is_streaming
        )
        if not tool_calls:
            return response

        tracker_config = self._build_tracker_config(config)

        tracker = self._session_trackers.get(session_id)
        if tracker is None:
            tracker = ToolCallTracker(config=tracker_config)
            self._session_trackers[session_id] = tracker
        elif tracker.config != tracker_config:
            tracker.config = tracker_config

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

    def _extract_tool_calls(
        self, content: Any, session_id: str, is_streaming: bool
    ) -> list[dict[str, Any]]:
        """Extract tool calls from response content.

        Args:
            content: The response content (can be a string or a dict)
            session_id: The active session identifier
            is_streaming: Whether the payload is part of a streaming response

        Returns:
            List of tool call dictionaries
        """
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
                        "Unsupported response content type for tool call extraction: %s",
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
                    self._streaming_tool_state.pop(session_id, None)
                    return result

            if is_streaming:
                pending = self._streaming_tool_state.setdefault(session_id, {})
                completed_indices: set[int] = set()

                for choice in choices:
                    delta = choice.get("delta", {})
                    if not isinstance(delta, dict):
                        continue

                    delta_tool_calls = delta.get("tool_calls")
                    if not delta_tool_calls or not isinstance(delta_tool_calls, list):
                        continue

                    for item in delta_tool_calls:
                        if not isinstance(item, dict):
                            continue

                        index = item.get("index", 0)
                        state = pending.setdefault(index, {"index": index})

                        for key, value in item.items():
                            if key == "function" and isinstance(value, dict):
                                function_state = state.setdefault("function", {})
                                for func_key, func_value in value.items():
                                    if func_value is not None:
                                        function_state[func_key] = func_value
                            elif key != "index" and value is not None:
                                state[key] = value

                        function_data = state.get("function", {})
                        if (
                            isinstance(function_data, dict)
                            and "arguments" in function_data
                        ):
                            completed_indices.add(index)

                    if choice.get("finish_reason") == "tool_calls":
                        completed_indices.update(pending.keys())

                completed_calls: list[dict[str, Any]] = []
                for index in sorted(completed_indices):
                    state = pending.get(index)
                    if not state:
                        continue

                    function_state = state.get("function", {})
                    if not isinstance(function_state, dict):
                        continue
                    if "arguments" not in function_state:
                        continue

                    call: dict[str, Any] = {
                        key: (dict(value) if isinstance(value, dict) else value)
                        for key, value in state.items()
                        if key != "index"
                    }
                    function_copy = call.get("function", {})
                    if isinstance(function_copy, dict) and "name" not in function_copy:
                        function_copy["name"] = "unknown"
                    call["function"] = function_copy
                    call["index"] = index
                    completed_calls.append(call)

                for index in completed_indices:
                    pending.pop(index, None)

                if not pending:
                    self._streaming_tool_state.pop(session_id, None)

                if completed_calls:
                    return completed_calls

        if isinstance(data, list) and all(  # type: ignore[unreachable]
            isinstance(item, dict) and "function" in item for item in data
        ):  # type: ignore[unreachable]
            return data  # type: ignore[unreachable]

        return []

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
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Invalid tool loop mode '%s' provided; falling back to break mode.",
                        mode_value,
                    )

        return ToolLoopMode.BREAK
