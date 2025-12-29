"""
Generation config building for Gemini Code Assist API.

This module handles building generationConfig including thinkingConfig
for models that support thinking/reasoning.
"""

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.core.domain.gemini_metadata import create_gemini_generation_config

logger = logging.getLogger(__name__)


class ThinkingConfig(BaseModel):
    """Thinking configuration for models that support reasoning."""

    thinkingBudget: int  # noqa: N815
    includeThoughts: bool = True  # noqa: N815

    model_config = ConfigDict(populate_by_name=True)


class GenerationConfigBuilder:
    """Builds generationConfig for Gemini Code Assist API requests.

    Handles:
    - Temperature, top_p, top_k parameters
    - Max output tokens
    - Thinking/reasoning configuration for thinking models
    """

    # Default reasoning effort to thinking budget mapping
    EFFORT_TO_BUDGET: dict[str, int] = {
        "low": 512,
        "medium": 2048,
        "high": -1,  # -1 means unlimited
    }

    DEFAULT_THINKING_BUDGET = 2048

    def build(self, request_data: Any) -> dict[str, Any]:
        """Build Code Assist generationConfig from request_data.

        Args:
            request_data: The request data containing generation parameters

        Returns:
            generationConfig dictionary ready for the API
        """
        # Extract parameters with defaults
        temperature = float(getattr(request_data, "temperature", 0.7))
        max_tokens = int(getattr(request_data, "max_tokens", 1024))
        top_p = float(getattr(request_data, "top_p", 0.95))
        top_k = getattr(request_data, "top_k", None)

        # Create generation config using Pydantic model
        config = create_gemini_generation_config(
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens,
            top_k=int(top_k) if top_k is not None else None,
        )

        # Convert to Gemini API format
        cfg = config.model_dump()

        # Convert field names to Code Assist API format
        if "max_output_tokens" in cfg:
            cfg["maxOutputTokens"] = cfg.pop("max_output_tokens")
        if "top_p" in cfg:
            cfg["topP"] = cfg.pop("top_p")
        if "top_k" in cfg:
            cfg["topK"] = cfg.pop("top_k")

        # Add thinkingConfig
        cfg["thinkingConfig"] = self._build_thinking_config(request_data)

        return cfg

    def _build_thinking_config(self, request_data: Any) -> ThinkingConfig:
        """Build thinkingConfig for thinking/reasoning support.

        Args:
            request_data: The request data containing thinking parameters

        Returns:
            ThinkingConfig model
        """
        thinking_budget = getattr(request_data, "thinking_budget", None)
        reasoning_effort = getattr(request_data, "reasoning_effort", None)

        # Map reasoning_effort to thinking_budget if thinking_budget not explicit
        if thinking_budget is None and reasoning_effort is not None:
            thinking_budget = self.EFFORT_TO_BUDGET.get(
                reasoning_effort.lower() if isinstance(reasoning_effort, str) else "",
                None,
            )

        # Default to medium thinking budget if not specified
        if thinking_budget is None:
            thinking_budget = self.DEFAULT_THINKING_BUDGET

        return ThinkingConfig(
            thinkingBudget=thinking_budget,
            includeThoughts=True,
        )


def build_code_assist_request_format(
    processed_messages: list[Any],
    model: str,
    generation_config: dict[str, Any],
) -> dict[str, Any]:
    """Convert OpenAI-style messages to Code Assist API format.

    Args:
        processed_messages: List of processed message dictionaries
        model: Model name to use
        generation_config: generationConfig dictionary

    Returns:
        Code Assist request format dictionary
    """
    # Extract the last user message for generation
    user_message = ""
    for msg in reversed(processed_messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        # Fallback to first message if no user message found
        user_message = (
            processed_messages[0].get("content", "") if processed_messages else ""
        )

    # Build system prompt from conversation history
    system_prompt = ""
    conversation_context = []

    for msg in processed_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            system_prompt = content
        elif role in ("user", "assistant"):
            # Avoid double-prefixing if the content already starts with a role label
            normalized = content.lstrip()
            lowered = normalized.lower()
            if lowered.startswith(("assistant:", "user:")):
                normalized = normalized.split(":", 1)[1].lstrip()
            prefix = "Assistant" if role == "assistant" else "User"
            conversation_context.append(f"{prefix}: {normalized}")

    # Combine system prompt with conversation context (optimized with join)
    if conversation_context:
        context_str = "\n".join(conversation_context)
        full_prompt = (
            f"{system_prompt}\n\n{context_str}" if system_prompt else context_str
        )
    else:
        full_prompt = system_prompt

    return {
        "model": model,
        "contents": [
            {"role": "user", "parts": [{"text": full_prompt or user_message}]}
        ],
        "generationConfig": generation_config,
    }


def convert_from_code_assist_format(
    code_assist_response: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """Convert Code Assist API response to OpenAI-compatible format.

    Args:
        code_assist_response: Raw Code Assist API response
        model: Model name for the response

    Returns:
        OpenAI-compatible response dictionary
    """
    import time

    # Extract the generated text from Code Assist response
    response_wrapper = code_assist_response.get("response", {})
    candidates = response_wrapper.get("candidates", [])
    generated_text = ""

    if candidates and len(candidates) > 0:
        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        if parts and len(parts) > 0:
            generated_text = parts[0].get("text", "")

    return {
        "id": f"code-assist-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": generated_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,  # Code Assist API doesn't provide token counts
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
