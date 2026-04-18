from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

# Cache tiktoken encoding for better performance
_tiktoken_encoding = None
_tiktoken_lock = threading.Lock()
_model_tokenizer_cache: dict[str, Any] = {}

_MODEL_TOKENIZER_FAMILIES: list[tuple[tuple[str, ...], str]] = [
    (("gpt-5", "gpt-4.1", "gpt-4o", "o1", "o3", "o4", "codex"), "o200k_base"),
    (
        (
            "claude",
            "gemini",
            "llama",
            "mistral",
            "mixtral",
            "deepseek",
            "qwen",
            "glm",
            "kimi",
            "yi",
            "minimax",
            "moonshot",
        ),
        "cl100k_base",
    ),
]


def _resolve_encoding_for_model(
    *,
    tiktoken_module: Any,
    model: str | None,
) -> Any:
    if not model:
        return tiktoken_module.get_encoding("cl100k_base")

    normalized_model = model.strip().lower()
    cached = _model_tokenizer_cache.get(normalized_model)
    if cached is not None:
        return cached

    family_encoding = "cl100k_base"
    for needles, encoding_name in _MODEL_TOKENIZER_FAMILIES:
        if any(needle in normalized_model for needle in needles):
            family_encoding = encoding_name
            break

    encoding = tiktoken_module.get_encoding(family_encoding)
    _model_tokenizer_cache[normalized_model] = encoding
    return encoding


async def count_tokens_async(text: str, model: str | None = None) -> int:
    """Count tokens for the provided text using tiktoken in a background thread.

    Offloads CPU-intensive tokenization to a thread pool to avoid blocking the
    event loop, especially for large texts (~170k-1M+ tokens).

    Args:
        text: The text to count tokens for
        model: Optional model name to select encoding (best-effort)

    Returns:
        Estimated number of tokens in the text
    """
    if not text:
        return 0
    return await asyncio.to_thread(count_tokens, text, model=model)


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

        if model and model.strip():
            import tiktoken  # type: ignore

            model_encoding = _resolve_encoding_for_model(
                tiktoken_module=tiktoken,
                model=model,
            )
            return len(model_encoding.encode(text))

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
        tool_calls = None

        if isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
            reasoning = m.get("reasoning_content")
            tool_calls = m.get("tool_calls")
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            reasoning = getattr(m, "reasoning_content", None)
            tool_calls = getattr(m, "tool_calls", None)

        # Basic role identification
        role_label = str(role) if role else "unknown"

        # Handle reasoning content if present
        if reasoning and isinstance(reasoning, str):
            parts.append(f"{role_label} (reasoning): {reasoning}")

        # Handle tool calls if present
        if tool_calls and isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    function = tc.get("function", {})
                    if isinstance(function, dict):
                        name = function.get("name", "unknown_tool")
                        args = function.get("arguments", "")
                        parts.append(f"{role_label} (tool_call): {name}({args})")
                elif hasattr(tc, "function"):
                    # Handle object with attributes
                    function = getattr(tc, "function", None)
                    name = (
                        getattr(function, "name", "unknown_tool")
                        if function
                        else "unknown_tool"
                    )
                    args = getattr(function, "arguments", "") if function else ""
                    parts.append(f"{role_label} (tool_call): {name}({args})")

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
