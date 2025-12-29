"""ReasoningMarkupProcessor service for processing reasoning markup tags.

This service extracts tag processing logic from HybridConnector to provide
focused, testable components for reasoning markup normalization, formatting, and extraction.

Requirements satisfied:
- Req2.4: ReasoningMarkupProcessor extraction
- Req 3: Protocol-first design
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText

from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText
from src.connectors.utils.model_capabilities import get_reasoning_tags


@dataclass(frozen=True, slots=True)
class ReasoningTexts:
    """Result of preparing reasoning texts for different formats.

    Attributes:
        tagged: The reasoning text with backend-specific tags/markup.
        plain: The plain text representation without tags/markup.
    """

    tagged: str
    plain: str


class ReasoningMarkupProcessor:
    """Service for processing reasoning markup tags.

    Handles normalization, formatting, and extraction of reasoning tags
    for various backend formats.
    """

    # Compiled regex patterns for tag detection
    _LEADING_REASONING_TAG = re.compile(
        r"^\s*<\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*", re.IGNORECASE
    )
    _TRAILING_REASONING_TAG = re.compile(
        r"\s*<\s*/\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def _truncate_after_reasoning_close(reasoning_output: str) -> str:
        """Trim reasoning output so that only the thinking segment remains."""
        closing_tags = ["</think>", "</thinking>", "</reason>", "</reasoning>"]
        for tag in closing_tags:
            index = reasoning_output.find(tag)
            if index != -1:
                return reasoning_output[: index + len(tag)]
        return reasoning_output

    @staticmethod
    def _assemble_reasoning_markup(
        opening_tag: str, closing_tag: str, body: str
    ) -> str:
        """Rebuild reasoning text with canonical tags."""
        if not body:
            return f"{opening_tag}{closing_tag}"

        if "\n" in body or body.startswith("<"):
            return f"{opening_tag}\n{body}\n{closing_tag}"

        return f"{opening_tag}{body}{closing_tag}"

    def _normalize_reasoning_markup(
        self, reasoning_output: str, opening_tag: str, closing_tag: str
    ) -> str:
        """Normalize reasoning markup to use canonical tags and ensure closure."""
        truncated = self._truncate_after_reasoning_close(reasoning_output)
        stripped = truncated.strip()
        if not stripped:
            return stripped

        leading_match = self._LEADING_REASONING_TAG.match(stripped)
        body_start = leading_match.end() if leading_match else 0
        body_section = stripped[body_start:]

        trailing_match = self._TRAILING_REASONING_TAG.search(body_section)
        if trailing_match:
            body_end = trailing_match.start()
            body_section = body_section[:body_end]

        body = body_section.strip()
        return self._assemble_reasoning_markup(opening_tag, closing_tag, body)

    def _apply_reasoning_tag_wrapping(
        self, reasoning_output: str, opening_tag: str, closing_tag: str
    ) -> str:
        """Wrap or normalize reasoning output using backend-specific tags."""
        return self._normalize_reasoning_markup(
            reasoning_output, opening_tag, closing_tag
        )

    @staticmethod
    def _extract_reasoning_inner_text(text: str) -> str:
        """Strip XML-like tags and return inner text for reasoning payloads."""
        if not text:
            return ""

        return re.sub(r"<[^>]+>", "", text).strip()

    def _prepare_reasoning_texts(
        self, reasoning_output: str, backend: str
    ) -> ReasoningTexts:
        """Return backend-tagged reasoning and plain text representations."""
        if not reasoning_output:
            return ReasoningTexts(tagged="", plain="")

        tags = get_reasoning_tags(backend)
        tagged = self._apply_reasoning_tag_wrapping(
            reasoning_output, tags.opening_tag, tags.closing_tag
        ).strip()

        plain = self._extract_reasoning_inner_text(tagged)
        if not plain:
            return ReasoningTexts(tagged="", plain="")

        return ReasoningTexts(tagged=tagged, plain=plain)

    def normalize(self, reasoning_output: str, backend: str) -> ReasoningText:
        """Normalize reasoning markup to canonical format.

        Args:
            reasoning_output: Raw reasoning text with potentially malformed tags
            backend: Backend name for tag format selection

        Returns:
            ReasoningText containing tagged and plain text representations
        """
        reasoning_texts = self._prepare_reasoning_texts(reasoning_output, backend)
        return ReasoningText(
            tagged=reasoning_texts.tagged,
            plain=reasoning_texts.plain,
            backend=backend,
        )

    def format_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning with backend-specific tags.

        Args:
            reasoning_output: Raw reasoning text
            backend: Backend name for format selection

        Returns:
            Formatted reasoning with appropriate tags
        """
        reasoning_texts = self._prepare_reasoning_texts(reasoning_output, backend)
        return reasoning_texts.tagged if reasoning_texts.plain else ""

    def extract_plain_text(self, reasoning_output: str) -> str:
        """Strip all tags and return plain text.

        Args:
            reasoning_output: Tagged reasoning text

        Returns:
            Plain text with all tags removed
        """
        return self._extract_reasoning_inner_text(reasoning_output)
