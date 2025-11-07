"""Model specification parsing for the hybrid connector."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HybridModelSpecMixin:
    """Provide hybrid model specification parsing helpers."""

    def _parse_hybrid_model_spec(
        self, model_spec: str
    ) -> tuple[str, str, dict[str, Any], str, str, dict[str, Any]]:
        """Parse hybrid model specification with optional URI parameters."""

        from src.core.domain.model_utils import parse_model_with_params

        # Remove "hybrid:" prefix if present
        if model_spec.startswith("hybrid:"):
            model_spec = model_spec[7:]

        # Check for brackets
        if not model_spec.startswith("[") or not model_spec.endswith("]"):
            raise ValueError(
                "Invalid hybrid model format. Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]. "
                "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            )

        # Remove brackets
        model_spec = model_spec[1:-1]

        # Split by comma - need to be careful with commas in query strings
        parts: list[str] = []
        current_part: list[str] = []

        i = 0
        while i < len(model_spec):
            char = model_spec[i]

            if char == ",":
                current_str = "".join(current_part)
                has_colon = ":" in current_str
                current_str.find("?")

                if has_colon:
                    parts.append(current_str)
                    current_part = []
                    i += 1
                    continue

            current_part.append(char)
            i += 1

        if current_part:
            parts.append("".join(current_part))

        if len(parts) != 2:
            raise ValueError(
                f"Invalid hybrid model format. Expected exactly 2 models separated by comma, got {len(parts)}. "
                "Expected: hybrid:[reasoning-backend:reasoning-model,execution-backend:execution-model]. "
                "Example: hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]"
            )

        reasoning_spec = parts[0].strip()
        execution_spec = parts[1].strip()

        try:
            reasoning_backend, reasoning_model, reasoning_params = (
                parse_model_with_params(reasoning_spec)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to parse reasoning model specification '%s': %s. Attempting to continue with fallback parsing.",
                reasoning_spec,
                exc,
            )
            raise ValueError(
                f"Invalid reasoning model specification: '{reasoning_spec}'. "
                f"Error: {exc}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: minimax:MiniMax-M2?temperature=0.8"
            ) from exc

        reasoning_backend = reasoning_backend.strip()
        reasoning_model = reasoning_model.strip()

        if not reasoning_backend or not reasoning_model:
            raise ValueError(
                f"Incomplete reasoning model specification: '{reasoning_spec}'. Both backend and model must be non-empty. "
                "Example: minimax:MiniMax-M2"
            )

        try:
            execution_backend, execution_model, execution_params = (
                parse_model_with_params(execution_spec)
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to parse execution model specification '%s': %s. Attempting to continue with fallback parsing.",
                execution_spec,
                exc,
            )
            raise ValueError(
                f"Invalid execution model specification: '{execution_spec}'. "
                f"Error: {exc}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: qwen-oauth:qwen3-coder-plus?temperature=0.3"
            ) from exc

        execution_backend = execution_backend.strip()
        execution_model = execution_model.strip()

        if not execution_backend or not execution_model:
            raise ValueError(
                f"Incomplete execution model specification: '{execution_spec}'. Both backend and model must be non-empty. "
                "Example: qwen-oauth:qwen3-coder-plus"
            )

        logger.debug(
            "Parsed hybrid model spec: reasoning=%s:%s (params=%s), execution=%s:%s (params=%s)",
            reasoning_backend,
            reasoning_model,
            reasoning_params,
            execution_backend,
            execution_model,
            execution_params,
        )

        return (
            reasoning_backend,
            reasoning_model,
            reasoning_params,
            execution_backend,
            execution_model,
            execution_params,
        )
