"""
Interface for tool-call reactor orchestrator.

This module defines the contract for the orchestrator that coordinates tool-call
processing across extraction, normalization, deduplication, parsing, fixups,
reactor invocation, and replacement creation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState


class ToolCallReactorContext(BaseModel):
    """Typed view over reactor context data passed between layers.

    This replaces cross-layer ad-hoc dictionary passing. The legacy pipeline may
    still hold an untyped mapping; an adapter should construct this model at the boundary.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    client_os: str | None = None
    """Detected client operating system."""

    stream_key: str | None = None
    """Stream identifier for lifecycle tracking."""

    buffer_state: IToolCallBufferState | None = None
    """Optional buffer state for streaming tool-call buffering."""


class IToolCallReactorOrchestrator(ABC):
    """Interface for orchestrating tool-call processing.

    The orchestrator coordinates the end-to-end flow of tool-call processing:
    - Bypass checks (bypass flag, VTC marker, no tool calls)
    - Extraction and normalization of tool calls
    - Deduplication and lifecycle tracking
    - Argument parsing and fixups
    - Reactor invocation
    - Replacement response creation for swallowed calls

    The orchestrator preserves fail-open behavior: exceptions during processing
    do not crash the request.
    """

    @abstractmethod
    async def handle(
        self,
        response: ProcessedResponse,
        session_id: str,
        context: ToolCallReactorContext,
        is_streaming: bool,
    ) -> ProcessedResponse:
        """Process a response for tool calls and return either original or replacement.

        This method orchestrates the complete tool-call processing flow:
        1. Checks bypass conditions (bypass flag, VTC marker)
        2. Extracts and normalizes tool calls from response
        3. Filters to new tool calls via deduplication
        4. For each new tool call:
           - Parses and fixes arguments
           - Invokes reactor (fail-open on exceptions)
           - Creates replacement response if swallowed
        5. Resets stream state if needed
        6. Returns original response if no swallows occurred

        Args:
            response: The response to process for tool calls.
            session_id: The session ID associated with the request.
            context: Typed reactor context with stream key and buffer state.
            is_streaming: Whether this is a streaming response.

        Returns:
            Either the original response (unchanged) or a replacement response
            if a tool call was swallowed. The replacement response is compatible
            with the middleware pipeline and includes required metadata keys.

        Preconditions:
            - ToolCallReactorContext is constructed at the boundary
            - buffer_state may be None (degraded mode)

        Postconditions:
            - Returned value is a ProcessedResponse compatible with middleware
            - Swallow decisions produce metadata keys required by retry/streaming processors
        """
        ...
