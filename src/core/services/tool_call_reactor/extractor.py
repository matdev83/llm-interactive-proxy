"""Tool-call extractor for tool-call reactor subsystem.

This module implements extraction of tool calls from various response shapes
(attributes, metadata, content) following a priority order and fail-open strategy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.interfaces.tool_call_extractor_interface import IToolCallExtractor

logger = logging.getLogger(__name__)


class ToolCallExtractor(IToolCallExtractor):
    """Extracts tool calls from response objects following priority order.

    This extractor attempts to extract tool calls from response objects following
    a priority order:
    1. Direct `tool_calls` attribute (if present and is a list)
    2. `metadata.tool_calls` (if attribute extraction found nothing)
    3. Parsed `content` attribute (if metadata extraction found nothing)

    The extractor returns raw tool-call objects (not normalized) and follows a
    fail-open strategy: exceptions during extraction do not crash the request.
    """

    def extract(self, response: Any) -> list[Any]:
        """Extract tool calls from a response object.

        This method attempts to extract tool calls from the response following
        a priority order. Returns raw tool-call objects that need to be normalized
        separately.

        Args:
            response: The response object to extract tool calls from.

        Returns:
            List of raw tool-call objects. Returns empty list if no tool calls
            are found or if extraction fails (fail-open behavior).
        """
        tool_calls: list[Any] = []

        # Priority 1: Direct 'tool_calls' attribute
        try:
            if (
                hasattr(response, "tool_calls")
                and response.tool_calls
                and isinstance(response.tool_calls, list)
            ):
                tool_calls.extend(response.tool_calls)
                return tool_calls
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Error extracting tool calls from attribute: %s",
                    e,
                    exc_info=True,
                )

        # Priority 2: 'tool_calls' within metadata
        if not tool_calls:
            try:
                metadata = getattr(response, "metadata", None)
                if metadata and isinstance(metadata, dict):
                    meta_calls = metadata.get("tool_calls")
                    if isinstance(meta_calls, list):
                        tool_calls.extend(meta_calls)
                        return tool_calls
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error extracting tool calls from metadata: %s",
                        e,
                        exc_info=True,
                    )

        # Priority 3: Extract from content
        if not tool_calls:
            try:
                content = getattr(response, "content", None)
                if content:
                    # Check if content is an object with tool_calls attribute (e.g., ChatMessage)
                    if hasattr(content, "tool_calls") and isinstance(
                        getattr(content, "tool_calls", None), list
                    ):
                        tool_calls.extend(content.tool_calls)
                    else:
                        extracted = self._extract_from_content(content)
                        tool_calls.extend(extracted)
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error extracting tool calls from content: %s",
                        e,
                        exc_info=True,
                    )

        return tool_calls

    def _extract_from_content(self, content: Any) -> list[Any]:
        """Extract tool calls from response content.

        Supports:
        - JSON string that can be parsed to dict/list
        - Dict with `choices[].message.tool_calls` structure
        - List of tool-call objects (direct list)

        Args:
            content: The content to extract from (string, dict, or list).

        Returns:
            List of raw tool-call objects found in content.
        """
        # Parse content if it's a string
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        elif isinstance(content, dict | list):
            data = content
        else:
            return []

        tool_calls: list[Any] = []

        # Handle dict with choices structure
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        message = choice.get("message", {})
                        if isinstance(message, dict):
                            message_tool_calls = message.get("tool_calls")
                            if (
                                isinstance(message_tool_calls, list)
                                and message_tool_calls
                                and all(
                                    isinstance(item, dict)
                                    for item in message_tool_calls
                                )
                            ):
                                tool_calls.extend(message_tool_calls)

        # Handle direct list of tool calls
        if (
            isinstance(data, list)
            and data
            and all(isinstance(item, dict) and "function" in item for item in data)
        ):
            tool_calls.extend(data)

        return tool_calls
