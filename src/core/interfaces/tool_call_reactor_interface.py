"""
Tool Call Reactor Interface.

This module defines interfaces for the tool call reactor system,
which provides event-driven architecture for reacting to tool calls
from remote LLMs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ToolCallContext:
    """Context information for a tool call event."""

    session_id: str
    """The session ID associated with the tool call."""

    backend_name: str
    """The name of the backend that generated the response."""

    model_name: str
    """The name of the model that generated the tool call."""

    full_response: Any
    """The full response from the LLM containing the tool call."""

    tool_name: str
    """The name of the tool being called."""

    tool_arguments: dict[str, Any]
    """The arguments passed to the tool call."""

    calling_agent: str | None = None
    """The name of the agent making the tool call (if available)."""

    timestamp: datetime | None = None
    """When the tool call was detected."""


@dataclass
class ToolCallReactionResult:
    """Result of a tool call reaction."""

    should_swallow: bool
    """Whether to swallow the tool call and prevent it from reaching the client."""

    replacement_response: str | None = None
    """If swallowing, the replacement response to send back to the LLM."""

    metadata: dict[str, Any] | None = None
    """Additional metadata about the reaction."""


class IToolCallHandler(ABC):
    """Interface for tool call event handlers.

    Tool call handlers can react to tool calls from remote LLMs and optionally
    swallow them to provide custom steering responses.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name of this handler."""

    @property
    @abstractmethod
    def priority(self) -> int:
        """The priority of this handler (higher numbers run first)."""

    @abstractmethod
    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler can process the given tool call.

        Args:
            context: The tool call context.

        Returns:
            True if this handler can process the tool call.
        """

    @abstractmethod
    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Handle the tool call event.

        Args:
            context: The tool call context.

        Returns:
            The reaction result indicating whether to swallow the tool call
            and any replacement response.
        """


class IToolCallReactor(ABC):
    """Interface for the tool call reactor system.

    The tool call reactor manages a collection of tool call handlers and
    orchestrates their execution when tool calls are detected.
    """

    @abstractmethod
    async def register_handler(self, handler: IToolCallHandler) -> None:
        """Register a tool call handler.

        Args:
            handler: The handler to register.
        """

    @abstractmethod
    async def unregister_handler(self, handler_name: str) -> None:
        """Unregister a tool call handler.

        Args:
            handler_name: The name of the handler to unregister.
        """

    @abstractmethod
    async def process_tool_call(
        self, context: ToolCallContext
    ) -> ToolCallReactionResult | None:
        """Process a tool call through all registered handlers.

        Args:
            context: The tool call context.

        Returns:
            The reaction result from the first handler that swallows the call,
            or None if no handler swallows it.
        """

    @abstractmethod
    def get_registered_handlers(self) -> list[str]:
        """Get the names of all registered handlers.

        Returns:
            List of handler names.
        """


class IToolCallHistoryTracker(ABC):
    """Interface for tracking tool call history."""

    @abstractmethod
    async def record_tool_call(
        self, session_id: str, tool_name: str, context: dict[str, Any]
    ) -> None:
        """Record a tool call in the history.

        Args:
            session_id: The session ID.
            tool_name: The name of the tool called.
            context: Additional context about the call.
        """

    @abstractmethod
    async def get_call_count(
        self, session_id: str, tool_name: str, time_window_seconds: int
    ) -> int:
        """Get the number of times a tool was called in a time window.

        Args:
            session_id: The session ID.
            tool_name: The name of the tool.
            time_window_seconds: The time window in seconds.

        Returns:
            The number of calls within the time window.
        """

    @abstractmethod
    async def clear_history(self, session_id: str | None = None) -> None:
        """Clear the call history.

        Args:
            session_id: Optional session ID to clear history for.
                       If None, clears all history.
        """
