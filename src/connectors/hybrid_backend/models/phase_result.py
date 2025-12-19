"""Reasoning phase result dataclass."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.response_processor_interface import ProcessedResponse


@dataclass
class ReasoningPhaseResult:
    """Container for reasoning phase outcome.

    This dataclass holds the result of executing the reasoning phase,
    including captured text, completion status, tool calls, and metadata.

    Attributes:
        text: Captured reasoning output text (with tags stripped)
        complete: Whether reasoning completed successfully (not timed out)
        tool_calls: Any tool calls requested by reasoning model
        raw_chunks: Raw processed response chunks for debugging/replay
        media_type: Response media type if available (e.g., "text/plain")
        headers: Response headers if available
    """

    text: str = ""
    complete: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_chunks: list["ProcessedResponse"] = field(default_factory=list)
    media_type: str | None = None
    headers: dict[str, str] | None = None

    def has_tool_calls(self) -> bool:
        """Check whether reasoning produced any tool calls.

        Returns:
            True if tool_calls list is non-empty, False otherwise
        """
        return bool(self.tool_calls)
