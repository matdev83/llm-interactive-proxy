from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.core.domain.chat import ChatMessage, MessageContentPartText


@dataclass(slots=True)
class TailSegment:
    """Result of extracting the last meaningful user segment."""

    content: str
    message_index: int | None
    part_index: int | None = None


class CommandTailExtractor:
    """Utility that isolates the actionable tail from the latest user message."""

    def extract_tail_segment(self, messages: Sequence[ChatMessage]) -> TailSegment:
        """Return the last non-blank text segment belonging to the latest user message."""
        for message_index in range(len(messages) - 1, -1, -1):
            message = messages[message_index]
            if message.role != "user":
                continue

            tail_text = self._extract_text_from_message(message)
            if tail_text is None:
                return TailSegment(content="", message_index=message_index)

            normalized_tail, part_index = tail_text
            return TailSegment(
                content=self._strip_trailing_lines(normalized_tail),
                message_index=message_index,
                part_index=part_index,
            )

        return TailSegment(content="", message_index=None)

    def _extract_text_from_message(
        self, message: ChatMessage
    ) -> tuple[str, int | None] | None:
        content = message.content
        if content is None:
            return None

        if isinstance(content, str):
            return content, None

        if isinstance(content, Sequence):
            for part_index in range(len(content) - 1, -1, -1):
                part = content[part_index]
                text_value = self._coerce_text(part)
                if text_value:
                    return text_value, part_index
            return "", None

        return str(content), None

    def _coerce_text(self, part: Any) -> str | None:
        if isinstance(part, MessageContentPartText):
            return part.text
        if isinstance(part, dict):
            text_value = part.get("text")
            return text_value if isinstance(text_value, str) else None
        return None

    def _strip_trailing_lines(self, text: str) -> str:
        if not text:
            return ""

        lines = text.splitlines()
        for line in reversed(lines):
            trimmed = line.strip()
            if trimmed:
                return trimmed
        return ""
