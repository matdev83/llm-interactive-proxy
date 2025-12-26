"""
Token estimation service for Gemini OAuth connectors.

This module provides async-safe token estimation using tiktoken,
wrapped in an injectable service to avoid global state and enable testing.
"""

import logging
import threading
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ITokenEstimator(Protocol):
    """Interface for token estimation."""

    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in the given text.

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated number of tokens.
        """
        ...

    def estimate_prompt_tokens(self, code_assist_request: dict[str, Any]) -> int | None:
        """Estimate prompt tokens from a Code Assist request.

        Args:
            code_assist_request: The prepared Code Assist request body.

        Returns:
            Estimated prompt token count, or None if estimation fails.
        """
        ...


@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    """Return cached tiktoken encoding instance.

    Uses lru_cache to ensure we only load the encoding once,
    reducing startup cost for subsequent calls.
    """
    import tiktoken  # type: ignore[import-untyped]

    return tiktoken.get_encoding("cl100k_base")


class TiktokenEstimator:
    """Token estimator using tiktoken's cl100k_base encoding.

    This estimator provides consistent token counting compatible with
    GPT-4 and similar models. It can be injected as a dependency
    for testing and mocking.
    """

    def __init__(self, encoding: Any | None = None) -> None:
        """Initialize the estimator.

        Args:
            encoding: Optional tiktoken encoding to use. If not provided,
                     uses the cached cl100k_base encoding.
        """
        self._encoding = encoding

    @property
    def encoding(self):
        """Get the tiktoken encoding, lazily initializing if needed."""
        if self._encoding is None:
            self._encoding = _get_tiktoken_encoding()
        return self._encoding

    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in the given text.

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated number of tokens.
        """
        try:
            return len(self.encoding.encode(text))
        except Exception as e:
            logger.warning("Failed to estimate tokens: %s", e)
            return 0

    def estimate_prompt_tokens(self, code_assist_request: dict[str, Any]) -> int | None:
        """Estimate prompt tokens from a Code Assist request.

        Extracts text from systemInstruction and contents fields,
        concatenates them, and counts tokens.

        Args:
            code_assist_request: The prepared Code Assist request body.

        Returns:
            Estimated prompt token count, or None if estimation fails.
        """
        try:
            prompt_text_parts: list[str] = []

            # Extract system instruction text
            system_instruction = code_assist_request.get("systemInstruction")
            if system_instruction:
                for part in system_instruction.get("parts", []):
                    if "text" in part:
                        prompt_text_parts.append(part["text"])

            # Extract content text
            for content in code_assist_request.get("contents", []):
                for part in content.get("parts", []):
                    if "text" in part:
                        prompt_text_parts.append(part["text"])

            if not prompt_text_parts:
                return None

            full_prompt = "\n".join(prompt_text_parts)
            return self.estimate_tokens(full_prompt)

        except Exception as e:
            logger.warning("Could not calculate prompt tokens: %s", e)
            return None


# Default instance for convenience (can be replaced in tests)
_default_estimator: TiktokenEstimator | None = None
_default_estimator_lock = threading.Lock()


def get_default_token_estimator() -> TiktokenEstimator:
    """Get the default token estimator instance.

    This function provides a module-level singleton for convenience,
    but the TiktokenEstimator class can also be instantiated directly
    for dependency injection.
    """
    global _default_estimator
    if _default_estimator is None:
        with _default_estimator_lock:
            if _default_estimator is None:
                _default_estimator = TiktokenEstimator()
    return _default_estimator


__all__ = [
    "ITokenEstimator",
    "TiktokenEstimator",
    "get_default_token_estimator",
]
