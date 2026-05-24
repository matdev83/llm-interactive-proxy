"""Interface for tool-call extraction from response objects.

This module defines the contract for components that extract tool calls
from various response shapes (attributes, metadata, content).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IToolCallExtractor(ABC):
    """Interface for extracting tool calls from response objects.

    This interface defines the contract for components that extract tool calls
    from various locations in response objects:
    - Direct `tool_calls` attribute (Priority 1)
    - `metadata.tool_calls` (Priority 2)
    - Parsed `content` attribute (Priority 3)

    The extractor returns raw tool-call objects (not normalized) and follows
    a fail-open strategy: exceptions during extraction do not crash the request.
    """

    @abstractmethod
    def extract(self, response: Any) -> list[Any]:
        """Extract tool calls from a response object.

        This method attempts to extract tool calls from the response following
        a priority order:
        1. Direct `tool_calls` attribute (if present and is a list)
        2. `metadata.tool_calls` (if attribute extraction found nothing)
        3. Parsed `content` attribute (if metadata extraction found nothing)

        The method returns raw tool-call objects (dicts, Pydantic models,
        dataclasses, etc.) that need to be normalized separately.

        Args:
            response: The response object to extract tool calls from.
                Can be any object with `tool_calls`, `metadata`, or `content` attributes.

        Returns:
            List of raw tool-call objects. Returns empty list if no tool calls
            are found or if extraction fails (fail-open behavior).

        Note:
            This method should not raise exceptions. If extraction fails,
            it should return an empty list and log at DEBUG level if needed.
        """
        ...
