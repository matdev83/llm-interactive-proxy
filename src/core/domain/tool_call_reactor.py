"""
Tool Call Reactor Domain Models.

This module contains domain models and entities for the tool call reactor system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ToolCallReactionMode(Enum):
    """Modes for tool call reaction."""

    PASSIVE = "passive"
    """Only observe the tool call, don't modify the response."""

    ACTIVE = "active"
    """Can swallow the tool call and provide replacement responses."""


@dataclass
class ToolCallHistoryEntry:
    """Entry in the tool call history."""

    session_id: str
    tool_name: str
    timestamp: datetime
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """Get the age of this entry in seconds."""
        return (datetime.now() - self.timestamp).total_seconds()


@dataclass
class ToolCallRateLimit:
    """Rate limiting configuration for tool call reactions."""

    calls_per_window: int
    """Maximum number of calls allowed in the time window."""

    window_seconds: int
    """Time window in seconds."""

    def __post_init__(self) -> None:
        """Validate the rate limit configuration."""
        if self.calls_per_window <= 0:
            raise ValueError("calls_per_window must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")


@dataclass
class ToolCallReactionConfig:
    """Configuration for a tool call reaction."""

    tool_name_pattern: str
    """Pattern to match tool names (supports wildcards)."""

    mode: ToolCallReactionMode = ToolCallReactionMode.ACTIVE
    """The reaction mode."""

    rate_limit: ToolCallRateLimit | None = None
    """Optional rate limiting configuration."""

    enabled: bool = True
    """Whether this reaction is enabled."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata for the reaction."""


@dataclass
class ToolCallSteeringResponse:
    """A steering response to send back to the LLM."""

    content: str
    """The content of the steering response."""

    role: str = "user"
    """The role to use for the response."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""


@dataclass
class ToolCallReaction:
    """A tool call reaction configuration with steering response."""

    config: ToolCallReactionConfig
    """The reaction configuration."""

    steering_response: ToolCallSteeringResponse
    """The steering response to send when swallowing the call."""

    name: str
    """Unique name for this reaction."""

    description: str | None = None
    """Optional description of this reaction."""


@dataclass
class ToolCallReactorStats:
    """Statistics for the tool call reactor."""

    total_tool_calls_processed: int = 0
    """Total number of tool calls processed."""

    tool_calls_swallowed: int = 0
    """Number of tool calls that were swallowed."""

    handlers_executed: int = 0
    """Number of handler executions."""

    rate_limits_hit: int = 0
    """Number of times rate limits were hit."""

    session_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per-session statistics."""

    def record_processed_call(self, session_id: str) -> None:
        """Record a processed tool call."""
        self.total_tool_calls_processed += 1
        if session_id not in self.session_stats:
            self.session_stats[session_id] = {}
        self.session_stats[session_id]["processed"] = (
            self.session_stats[session_id].get("processed", 0) + 1
        )

    def record_swallowed_call(self, session_id: str) -> None:
        """Record a swallowed tool call."""
        self.tool_calls_swallowed += 1
        if session_id not in self.session_stats:
            self.session_stats[session_id] = {}
        self.session_stats[session_id]["swallowed"] = (
            self.session_stats[session_id].get("swallowed", 0) + 1
        )

    def record_rate_limit_hit(self, session_id: str) -> None:
        """Record a rate limit hit."""
        self.rate_limits_hit += 1
        if session_id not in self.session_stats:
            self.session_stats[session_id] = {}
        self.session_stats[session_id]["rate_limits"] = (
            self.session_stats[session_id].get("rate_limits", 0) + 1
        )
