from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

# Cache tiktoken encoding for better performance
_tiktoken_encoding = None
_tiktoken_lock = threading.Lock()


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens for the provided text using tiktoken when available.

    Falls back to a heuristic (len(text)//4) if tiktoken isn't available.

    Args:
        text: The text to count tokens for
        model: Optional model name to select encoding (best-effort)

    Returns:
        Estimated number of tokens in the text
    """
    global _tiktoken_encoding

    if not text:
        return 0

    try:
        # Lazy load and cache tiktoken encoding for better performance
        # Use double-checked locking to avoid race conditions
        # NOTE: threading.Lock is safe here because the critical section is minimal
        # (only import and get_encoding, no I/O or blocking operations)
        # After initialization, no lock is needed (fast path)
        if _tiktoken_encoding is None:
            with _tiktoken_lock:
                # Check again inside the lock to avoid duplicate initialization
                if _tiktoken_encoding is None:
                    import tiktoken  # type: ignore

                    _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")

        return len(_tiktoken_encoding.encode(text))
    except (ImportError, AttributeError, TypeError, KeyError):
        logger.debug(
            "Token counting fallback engaged: tiktoken unavailable or error",
            exc_info=True,
        )
        return max(1, len(text) // 4)


def extract_prompt_text(messages: list[Any]) -> str:
    """Extract a flat prompt text from OpenAI-style messages."""
    if not messages:
        return ""

    parts: list[str] = []
    for m in messages:
        role = None
        content = None
        reasoning = None

        if isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
            reasoning = m.get("reasoning_content")
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            reasoning = getattr(m, "reasoning_content", None)

        # Basic role identification
        role_label = str(role) if role else "unknown"

        # Handle reasoning content if present
        if reasoning and isinstance(reasoning, str):
            parts.append(f"{role_label} (reasoning): {reasoning}")

        # Handle primary content
        if isinstance(content, str):
            parts.append(f"{role_label}: {content}")
        elif isinstance(content, Sequence) and not isinstance(content, str | bytes):
            # Concatenate text parts only
            for p in content:
                p_type = None
                p_text = None

                if isinstance(p, dict):
                    p_type = p.get("type")
                    p_text = p.get("text")
                else:
                    # Handle Pydantic models or other objects
                    p_type = getattr(p, "type", None)
                    p_text = getattr(p, "text", None)
                    # Fallback for models that might use 'content' key in parts
                    if not p_text and p_type == "text":
                        p_text = getattr(p, "content", None)

                if p_type == "text" and isinstance(p_text, str):
                    parts.append(f"{role_label}: {p_text}")
                elif p_type is None and isinstance(p, str):
                    # Direct string in a list of parts
                    parts.append(f"{role_label}: {p}")
                elif p_type == "text" and p_text is None:
                    # Case where type is text but text is missing, try to stringify
                    parts.append(f"{role_label}: {p!s}")
        elif content is not None:
            # Fallback for unknown content types
            parts.append(f"{role_label}: {content!s}")

    result = "\n".join(parts)
    if not result and messages:
        # Final desperate attempt: stringify everything
        try:
            result = str(messages)
            logger.debug("extract_prompt_text falling back to str(messages)")
        except Exception:
            pass
            
    return result
