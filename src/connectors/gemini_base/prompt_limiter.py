"""
Prompt limit enforcement for Gemini OAuth connectors.

This module provides functionality for:
- Estimating prompt token counts
- Enforcing prompt size limits
- Model-specific limit configuration
"""

import json
import logging
from typing import Any

from src.connectors.gemini_base.config import (
    CODE_ASSIST_PROMPT_LIMIT_MARGIN,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
)
from src.core.common.exceptions import InvalidRequestError

logger = logging.getLogger(__name__)


def serialize_part(part: Any) -> str | None:
    """Serialize a content part to string for token estimation.

    Args:
        part: A content part (dict, string, bytes, or other).

    Returns:
        String representation of the part, or None if empty.
    """
    if isinstance(part, dict):
        text_value = part.get("text")
        if isinstance(text_value, str):
            return text_value
        try:
            return json.dumps(part, ensure_ascii=False, default=str)
        except Exception:
            # Fallback to repr if JSON serialization fails
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to serialize content part to JSON, using repr",
                    exc_info=True,
                )
            return repr(part)
    if isinstance(part, str | bytes):
        return part.decode("utf-8", "ignore") if isinstance(part, bytes) else part
    if part is None:
        return None
    return str(part)


def estimate_prompt_tokens(
    code_assist_request: dict[str, Any],
    encoding: Any,
) -> int | None:
    """Best-effort estimate of prompt token usage for a Code Assist request.

    Args:
        code_assist_request: The Code Assist API request body.
        encoding: A tiktoken encoding instance.

    Returns:
        Estimated token count, or None if estimation fails.
    """
    prompt_text_parts: list[str] = []
    try:
        system_instruction = code_assist_request.get("systemInstruction")
        if isinstance(system_instruction, dict):
            for part in system_instruction.get("parts", []):
                serialized = serialize_part(part)
                if serialized:
                    prompt_text_parts.append(serialized)

        for content in code_assist_request.get("contents", []):
            if not isinstance(content, dict):
                continue
            for part in content.get("parts", []):
                serialized = serialize_part(part)
                if serialized:
                    prompt_text_parts.append(serialized)

        generation_config = code_assist_request.get("generationConfig")
        if generation_config:
            try:
                prompt_text_parts.append(
                    json.dumps(generation_config, ensure_ascii=False)
                )
            except Exception:
                # Fallback to repr if JSON serialization fails
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to serialize generation_config to JSON, using repr",
                        exc_info=True,
                    )
                prompt_text_parts.append(repr(generation_config))

        for extra_key in ("tools", "toolConfig", "safetySettings"):
            extra_value = code_assist_request.get(extra_key)
            if extra_value:
                try:
                    prompt_text_parts.append(
                        json.dumps(extra_value, ensure_ascii=False)
                    )
                except Exception:
                    # Fallback to repr if JSON serialization fails
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to serialize %s to JSON, using repr",
                            extra_key,
                            exc_info=True,
                        )
                    prompt_text_parts.append(repr(extra_value))

        if not prompt_text_parts:
            return 0

        full_prompt = "\n".join(prompt_text_parts)
        return len(encoding.encode(full_prompt))
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning("Failed to estimate prompt tokens: %s", exc)
        return None


def normalize_model_key(model_name: str) -> str:
    """Normalize model identifiers for prompt-limit lookups.

    Handles various model name formats including:
    - Provider prefixes (e.g., "provider:model")
    - Models/ prefix (e.g., "models/gemini-pro")

    Args:
        model_name: The model name to normalize.

    Returns:
        Normalized lowercase model name for consistent lookups.
    """
    normalized = (model_name or "").strip().lower()
    if ":" in normalized:
        normalized = normalized.split(":", 1)[-1]
    if normalized.startswith("models/"):
        normalized = normalized[len("models/") :]
    return normalized


def get_prompt_limit(
    effective_model: str,
    prompt_limit_overrides: dict[str, int],
    prompt_limit_prefix_overrides: tuple[tuple[str, int], ...],
    default_limit: int = DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    context_window_override: int | None = None,
) -> int | None:
    """Resolve the prompt-size threshold for the given model.

    Args:
        effective_model: The model name to get limit for.
        prompt_limit_overrides: Dict of exact model name to limit mappings.
        prompt_limit_prefix_overrides: Tuple of (prefix, limit) for prefix matching.
        default_limit: Default limit if no override matches.
        context_window_override: Optional config override for context window.

    Returns:
        The prompt limit in tokens, or None if no limit applies.
    """
    normalized = normalize_model_key(effective_model)

    limit = prompt_limit_overrides.get(normalized)

    if limit is None:
        for prefix, candidate_limit in prompt_limit_prefix_overrides:
            if normalized.startswith(prefix):
                limit = candidate_limit
                break

    if limit is None:
        limit = default_limit

    if isinstance(context_window_override, int) and context_window_override > 0:
        if limit is None:
            limit = context_window_override
        else:
            limit = min(limit, context_window_override)

    if limit is None or limit <= 0:
        return None

    return int(limit)


def enforce_prompt_limit(
    prompt_tokens: int | None,
    effective_model: str,
    limit: int | None,
    request_id: str | None = None,
) -> None:
    """Prevent Code Assist requests that would exceed the plan allowance.

    Args:
        prompt_tokens: Estimated token count for the prompt.
        effective_model: The model being used.
        limit: The prompt limit in tokens.
        request_id: Optional request ID for error details.

    Raises:
        InvalidRequestError: If prompt exceeds the limit.
    """
    if prompt_tokens is None:
        return

    if limit is None or limit <= 0:
        return

    # Apply safety margin (e.g., 0.97 means allow up to 97% of limit)
    soft_limit = int(limit * CODE_ASSIST_PROMPT_LIMIT_MARGIN)
    if soft_limit <= 0:
        soft_limit = limit

    if prompt_tokens <= soft_limit:
        return

    message = (
        "Estimated prompt size exceeds the Code Assist plan allowance. "
        "Please compress the conversation history or trim the request."
    )
    details: dict[str, Any] = {
        "model": effective_model,
        "estimated_tokens": prompt_tokens,
        "limit": limit,
        "status": "CONTEXT_WINDOW_WILL_OVERFLOW",
        "advice": (
            "Use /compress or start a new session to reduce history size before retrying."
        ),
    }
    if request_id:
        details["request_id"] = request_id

    logger.warning(
        "Code Assist prompt blocked locally: estimated_tokens=%s limit=%s model=%s",
        prompt_tokens,
        limit,
        effective_model,
    )

    raise InvalidRequestError(
        message=message,
        details=details,
        code="context_window_will_overflow",
    )


__all__ = [
    "enforce_prompt_limit",
    "estimate_prompt_tokens",
    "get_prompt_limit",
    "normalize_model_key",
    "serialize_part",
]
