from __future__ import annotations

import logging

from pydantic import ConfigDict, field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration import ILoopDetectionConfig
from src.tool_call_loop.config import ToolLoopMode
from src.tool_call_loop.tracker import ToolCallTracker

logger = logging.getLogger(__name__)


class LoopDetectionConfiguration(ValueObject):
    """Configuration for loop detection.
    
    This class handles both standard loop detection and tool call loop detection
    settings.
    """
    
    loop_detection_enabled: bool = True
    tool_loop_detection_enabled: bool = True
    min_pattern_length: int = 100
    max_pattern_length: int = 8000
    
    # Tool call loop detection settings
    tool_loop_max_repeats: int | None = None
    tool_loop_ttl_seconds: int | None = None
    tool_loop_mode: ToolLoopMode | None = None
    
    # Tool call tracker (not persisted)
    # This is mutable state that would be stored elsewhere in a proper implementation
    tool_call_tracker: ToolCallTracker | None = None
    
    @classmethod
    @field_validator("tool_loop_max_repeats")
    def validate_tool_loop_max_repeats(cls, v: int | None) -> int | None:
        """Validate that max repeats is at least 2."""
        if v is not None and v < 2:
            raise ValueError("Tool call loop max repeats must be at least 2")
        return v
    
    @classmethod
    @field_validator("tool_loop_ttl_seconds")
    def validate_tool_loop_ttl_seconds(cls, v: int | None) -> int | None:
        """Validate that TTL seconds is at least 1."""
        if v is not None and v < 1:
            raise ValueError("Tool call loop TTL seconds must be at least 1")
        return v
    
    def with_loop_detection_enabled(self, enabled: bool) -> LoopDetectionConfiguration:
        """Create a new config with updated loop detection enabled flag."""
        return self.model_copy(update={"loop_detection_enabled": enabled})
    
    def with_tool_loop_detection_enabled(self, enabled: bool) -> LoopDetectionConfiguration:
        """Create a new config with updated tool loop detection enabled flag."""
        return self.model_copy(update={"tool_loop_detection_enabled": enabled})
    
    def with_pattern_length_range(self, min_length: int, max_length: int) -> LoopDetectionConfiguration:
        """Create a new config with updated pattern length range."""
        return self.model_copy(
            update={"min_pattern_length": min_length, "max_pattern_length": max_length}
        )
    
    def with_tool_loop_max_repeats(self, max_repeats: int) -> LoopDetectionConfiguration:
        """Create a new config with updated tool loop max repeats."""
        return self.model_copy(update={"tool_loop_max_repeats": max_repeats})
    
    def with_tool_loop_ttl_seconds(self, ttl_seconds: int) -> LoopDetectionConfiguration:
        """Create a new config with updated tool loop TTL seconds."""
        return self.model_copy(update={"tool_loop_ttl_seconds": ttl_seconds})
    
    def with_tool_loop_mode(self, mode: ToolLoopMode) -> LoopDetectionConfiguration:
        """Create a new config with updated tool loop mode."""
        return self.model_copy(update={"tool_loop_mode": mode})