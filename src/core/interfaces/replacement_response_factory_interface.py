"""
Interface for replacement response factory.

This module defines the contract for building replacement responses when tool calls
are swallowed by policy, ensuring client safety and downstream compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from src.core.domain.chat import ToolCall
from src.core.interfaces.response_processor_interface import ProcessedResponse


class ToolCallReactionMetadata(BaseModel):
    """Typed metadata emitted by the reactor for observability and retries."""

    model_config = ConfigDict(extra="forbid")

    reaction_type: str
    """Type of reaction (e.g., 'swallowed', 'allowed', 'modified')."""

    reactor_name: str | None = None
    """Name of the reactor handler that produced this reaction."""


class IReplacementResponseFactory(ABC):
    """Interface for building replacement responses for swallowed tool calls.

    This factory is responsible for creating client-safe replacement responses
    that preserve downstream compatibility while avoiding exposure of internal
    steering identifiers to clients.
    """

    @abstractmethod
    def build_replacement(
        self,
        original_response: ProcessedResponse,
        replacement_content: str,
        original_tool_call: ToolCall,
        reaction_metadata: ToolCallReactionMetadata | None = None,
    ) -> ProcessedResponse:
        """Build a replacement response for a swallowed tool call.

        Args:
            original_response: The original response that contained the tool call.
            replacement_content: The steering message to include in the replacement.
            original_tool_call: The tool call that was swallowed.
            reaction_metadata: Optional metadata about the reactor's reaction.

        Returns:
            A ProcessedResponse compatible with the middleware pipeline that:
            - Contains client-safe content (no internal steering identifiers)
            - Sets required metadata keys for downstream processing
            - Preserves bounded original content for retry logic
            - Sets the _steering_replacement marker for streaming accumulation reset
        """
        ...
