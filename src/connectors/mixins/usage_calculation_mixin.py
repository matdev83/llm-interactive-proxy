"""Mixin for automatic usage calculation in backend connectors.

This mixin ensures that all backend connectors return usage information,
either from the backend response or calculated using tiktoken.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.responses import ResponseEnvelope

logger = logging.getLogger(__name__)


class UsageCalculationMixin:
    """Mixin to ensure usage is always present in responses.

    This mixin provides automatic usage calculation for connectors that
    may not receive usage information from their backend APIs.
    """

    def ensure_usage_in_response(
        self,
        response_envelope: ResponseEnvelope,
        request_messages: list[Any],
        model_name: str,
    ) -> ResponseEnvelope:
        """Ensure usage information is present in the response envelope.

        If usage is missing or has zero values, calculates it using tiktoken.

        Args:
            response_envelope: The response from the backend
            request_messages: The original request messages
            model_name: The model name used for the request

        Returns:
            ResponseEnvelope with usage information
        """
        # Check if usage needs to be calculated
        should_calculate = False

        if not response_envelope.usage:
            should_calculate = True
            logger.debug(
                f"No usage information in response from {model_name}, will calculate"
            )
        else:
            # Check for zero values
            prompt_tokens = response_envelope.usage.get("prompt_tokens", 0)
            completion_tokens = response_envelope.usage.get("completion_tokens", 0)
            total_tokens = response_envelope.usage.get("total_tokens", 0)

            if prompt_tokens == 0 or completion_tokens == 0 or total_tokens == 0:
                should_calculate = True
                logger.debug(
                    f"Zero usage values detected in response from {model_name}, will calculate"
                )

        if should_calculate:
            calculated_usage = self._calculate_usage_from_content(
                response_envelope, request_messages, model_name
            )
            response_envelope.usage = calculated_usage

        return response_envelope

    def _calculate_usage_from_content(
        self,
        response_envelope: ResponseEnvelope,
        request_messages: list[Any],
        model_name: str,
    ) -> dict[str, int]:
        """Calculate token usage from request and response content.

        This calculates tokens based on what was ACTUALLY sent/received,
        accounting for any proxy transformations.

        Args:
            response_envelope: The response envelope
            request_messages: The request messages (after transformations)
            model_name: The model name

        Returns:
            Dictionary with prompt_tokens, completion_tokens, and total_tokens
        """
        from src.core.utils.token_count import count_tokens, extract_prompt_text

        try:
            # Calculate prompt tokens from ACTUAL messages sent to backend
            # (after any proxy transformations)
            prompt_text = extract_prompt_text(request_messages)
            prompt_tokens = count_tokens(prompt_text, model=model_name)

            # Calculate completion tokens from response content
            completion_tokens = self._extract_completion_tokens(
                response_envelope.content, model_name
            )

            total_tokens = prompt_tokens + completion_tokens

            calculated_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }

            logger.info(
                f"Calculated usage for {model_name}: "
                f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            )

            return calculated_usage

        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "Failed to calculate usage for %s", model_name, exc_info=True
            )
            # Return zero usage as fallback
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

    def _extract_completion_tokens(self, response_content: Any, model_name: str) -> int:
        """Extract completion tokens from response content.

        Args:
            response_content: The response content (dict or other)
            model_name: The model name

        Returns:
            Number of completion tokens
        """
        from src.core.utils.token_count import count_tokens

        try:
            # Handle dict responses (OpenAI-style)
            if isinstance(response_content, dict):
                # Try to extract text from choices
                choices = response_content.get("choices", [])
                if choices and isinstance(choices, list):
                    first_choice = choices[0]
                    if isinstance(first_choice, dict):
                        # Non-streaming: message.content
                        message = first_choice.get("message", {})
                        if isinstance(message, dict):
                            content = message.get("content")
                            if isinstance(content, str):
                                return count_tokens(content, model=model_name)

                        # Streaming: delta.content
                        delta = first_choice.get("delta", {})
                        if isinstance(delta, dict):
                            content = delta.get("content")
                            if isinstance(content, str):
                                return count_tokens(content, model=model_name)

                # Try direct content field
                content = response_content.get("content")
                if isinstance(content, str):
                    return count_tokens(content, model=model_name)

            # Handle string responses
            elif isinstance(response_content, str):
                return count_tokens(response_content, model=model_name)

            # Handle Pydantic models
            elif hasattr(response_content, "model_dump"):
                return self._extract_completion_tokens(
                    response_content.model_dump(), model_name
                )

            return 0

        except (ValueError, TypeError, AttributeError, KeyError):
            logger.debug("Failed to extract completion tokens", exc_info=True)
            return 0
