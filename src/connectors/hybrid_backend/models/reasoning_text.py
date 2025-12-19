"""Reasoning text with tagged and plain representations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningText:
    """Encapsulates reasoning text in multiple formats.

    This dataclass provides both tagged (backend-specific markup) and
    plain (tag-stripped) representations of reasoning output. This
    dual representation enables:
    - Tagged: Injection into execution model context with proper formatting
    - Plain: Display to clients without reasoning tags

    Attributes:
        tagged: Reasoning with backend-specific tags (e.g., <think>...</think>)
        plain: Plain text with all tags stripped for client display
        backend: Source backend name for tag format selection (e.g., "openai", "anthropic")
    """

    tagged: str
    plain: str
    backend: str
