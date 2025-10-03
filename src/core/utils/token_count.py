from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens for the provided text using tiktoken when available.

    Falls back to a heuristic (len(text)//4) if tiktoken isn't available.

    Args:
        text: The text to count tokens for
        model: Optional model name to select encoding (best-effort)

    Returns:
        Estimated number of tokens in the text
    """
    try:
        import tiktoken  # type: ignore

        # Map to cl100k_base as a safe default
        encoding_name = "cl100k_base"
        try:
            enc = tiktoken.get_encoding(encoding_name)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception as e:
        logger.debug("Token counting fallback engaged: %s", e)
        return max(1, len(text) // 4)


def extract_prompt_text(messages: list[Any]) -> str:
    """Extract a flat prompt text from OpenAI-style messages."""
    parts: list[str] = []
    for m in messages:
        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if isinstance(m, dict):
            role = m.get("role", role)
            content = m.get("content", content)
        if isinstance(content, str):
            parts.append(f"{role}: {content}")
        elif isinstance(content, list):
            # Concatenate text parts only
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(f"{role}: {p.get('text','')}")
    return "\n".join(parts)
