"""Reasoning markup helpers for the hybrid connector."""

from __future__ import annotations

import logging
import re

from src.connectors.utils.model_capabilities import get_reasoning_tags

logger = logging.getLogger(__name__)


class HybridReasoningMarkupMixin:
    """Utilities for working with reasoning markup."""

    _LEADING_REASONING_TAG = re.compile(
        r"^\s*<\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*", re.IGNORECASE
    )
    _TRAILING_REASONING_TAG = re.compile(
        r"\s*<\s*/\s*(?:think|thinking|reason|reasoning)\b[^>]*>\s*$",
        re.IGNORECASE,
    )

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

    def _truncate_after_reasoning_close(self, reasoning_output: str) -> str:
        """Trim reasoning output so that only the thinking segment remains."""

        closing_tags = ["</think>", "</thinking>", "</reason>", "</reasoning>"]
        for tag in closing_tags:
            index = reasoning_output.find(tag)
            if index != -1:
                return reasoning_output[: index + len(tag)]
        return reasoning_output

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

    def _has_reasoning_content(self, formatted_reasoning: str) -> bool:
        """Determine whether the formatted reasoning contains substantive text."""

        return bool(self._extract_reasoning_inner_text(formatted_reasoning))

    def _prepare_reasoning_texts(
        self, reasoning_output: str, backend: str
    ) -> tuple[str, str]:
        """Return backend-tagged reasoning and plain text representations."""

        if not reasoning_output:
            return "", ""

        opening_tag, closing_tag = get_reasoning_tags(backend)
        tagged_reasoning = self._apply_reasoning_tag_wrapping(
            reasoning_output, opening_tag, closing_tag
        )
        plain_text = self._extract_reasoning_inner_text(tagged_reasoning)
        return tagged_reasoning, plain_text
