"""Tool-call normalizer for tool-call reactor subsystem.

This module implements normalization of tool-call objects from various
representations (dicts, Pydantic models, dataclasses) into a consistent
dictionary format following a fail-open strategy.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from src.core.interfaces.tool_call_normalizer_interface import (
    IToolCallNormalizer,
    NormalizedToolCallDict,
)

logger = logging.getLogger(__name__)


class ToolCallNormalizer(IToolCallNormalizer):
    """Normalizes tool-call objects to dictionary format.

    This normalizer converts tool-call objects from various representations
    into a consistent dictionary format. Supported input types:
    - Dictionary objects (already normalized, returned as-is)
    - Pydantic models (converted using `model_dump()`)
    - Dataclass instances (converted using `asdict()`)

    The normalizer follows a fail-open strategy: un-normalizable objects are
    skipped (returns None) without crashing the request.
    """

    def normalize(self, tool_call: Any) -> NormalizedToolCallDict | None:
        """Normalize a tool-call object into a dictionary.

        This method attempts to normalize a tool-call object into a consistent
        dictionary format. It supports dictionaries, Pydantic models, and dataclasses.

        The expected output shape matches NormalizedToolCall, which defines the
        canonical structure with id, type, and function fields.

        Args:
            tool_call: The tool-call object to normalize. Can be a dict,
                Pydantic model, dataclass, or any other object.

        Returns:
            Normalized dictionary representation of the tool call, or None
            if the object cannot be normalized (fail-open behavior).
        """
        # If already a dict, return as-is
        if isinstance(tool_call, dict):
            return tool_call

        # If it's a Pydantic model, use model_dump
        if hasattr(tool_call, "model_dump"):
            try:
                result = tool_call.model_dump()
                if isinstance(result, dict):
                    return result
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Pydantic model_dump() returned non-dict: %s",
                        type(result).__name__,
                    )
                return None
            except (TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert Pydantic model to dict: %s",
                        e,
                        exc_info=True,
                    )
                return None

        # If it's a dataclass, convert to dict
        if is_dataclass(tool_call) and not isinstance(tool_call, type):
            try:
                return asdict(tool_call)
            except (TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert dataclass to dict: %s",
                        e,
                        exc_info=True,
                    )
                return None

        # Otherwise, we can't normalize it
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Cannot normalize tool call object: %s",
                type(tool_call).__name__,
                exc_info=True,
            )
        return None
