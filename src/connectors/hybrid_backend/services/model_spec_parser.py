"""ModelSpecParser service for parsing hybrid model specification strings.

This service extracts the parsing logic from HybridConnector to provide
a focused, testable component for parsing hybrid model specifications.

Requirements satisfied:
- Req 2.1: ModelSpecParser extraction
- Req 3: Protocol-first design
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec

from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec

logger = logging.getLogger(__name__)


class ModelSpecParser:
    """Service for parsing hybrid model specification strings.

    Parses strings in the format:
    hybrid:[reasoning-backend:reasoning-model?params,execution-backend:execution-model?params]

    Example:
        hybrid:[minimax:MiniMax-M2?temperature=0.8,qwen-oauth:qwen3-coder-plus?temperature=0.3]
    """

    def parse(self, model_spec: str) -> HybridModelSpec:
        """Parse hybrid model specification with optional URI parameters.

        Args:
            model_spec: Format "hybrid:[reasoning-backend:reasoning-model?params,execution-backend:execution-model?params]"
                       Example: "hybrid:[minimax:MiniMax-M2?temperature=0.8,qwen-oauth:qwen3-coder-plus?temperature=0.3]"

        Returns:
            HybridModelSpec containing backend, model, and params for both phases.

        Raises:
            ValueError: If format is invalid or incomplete with descriptive messages and examples
        """
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
        # Strategy: Split by comma, but track if we're inside a query string
        # A comma inside a query string (after ?) should not split the models
        # We need to find the comma that separates the two model specs
        parts = []
        current_part: list[str] = []

        i = 0
        while i < len(model_spec):
            char = model_spec[i]

            # Check if this is a comma that separates models
            # It should be a comma that's not part of a query string
            if char == ",":
                # Look back to see if we're in a query string
                # A comma is a separator if there's no '?' before it in the current part
                # or if there's a complete backend:model before it
                current_str = "".join(current_part)

                # Check if we have a complete model spec (backend:model with optional ?params)
                # by checking if there's a colon before any question mark
                has_colon = ":" in current_str
                question_mark_pos = current_str.find("?")

                # If we're inside a query string (after ?), check if next part is a new model
                if question_mark_pos != -1:
                    # Look ahead to see if after this comma there's a backend:model pattern
                    # If yes, this comma separates models. If no, it's part of the param value.
                    remaining = model_spec[i + 1 :]
                    # Check if remaining starts with something like "backend:model"
                    # by looking for a colon after some non-comma characters
                    if ":" in remaining:
                        colon_pos = remaining.find(":")
                        # If colon is before any space or other separator, likely a new model
                        if colon_pos > 0 and colon_pos < len(remaining):
                            # Check if there are valid chars before colon (backend name)
                            before_colon = remaining[:colon_pos].strip()
                            if before_colon and "," not in before_colon:
                                # This looks like a new model spec, so split here
                                parts.append(current_str)
                                current_part = []
                                i += 1
                                continue

                    # Otherwise, comma is part of param value
                    current_part.append(char)
                    i += 1
                    continue

                if has_colon:
                    # This looks like a complete model spec, so this comma is a separator
                    parts.append(current_str)
                    current_part = []
                    i += 1
                    continue

            current_part.append(char)
            i += 1

        # Add the last part
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

        # Parse reasoning model spec with URI parameters
        try:
            reasoning_backend, reasoning_model, reasoning_params = (
                parse_model_with_params(reasoning_spec)
            )
        except Exception as e:
            # Log warning about parsing failure but provide helpful error message
            logger.warning(
                f"Failed to parse reasoning model specification '{reasoning_spec}': {e}. "
                f"Attempting to continue with fallback parsing."
            )
            raise ValueError(
                f"Invalid reasoning model specification: '{reasoning_spec}'. "
                f"Error: {e}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: minimax:MiniMax-M2?temperature=0.8"
            ) from e

        reasoning_backend = reasoning_backend.strip()
        reasoning_model = reasoning_model.strip()

        if not reasoning_backend or not reasoning_model:
            raise ValueError(
                f"Incomplete reasoning model specification: '{reasoning_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: minimax:MiniMax-M2"
            )

        # Parse execution model spec with URI parameters
        try:
            execution_backend, execution_model, execution_params = (
                parse_model_with_params(execution_spec)
            )
        except Exception as e:
            # Log warning about parsing failure but provide helpful error message
            logger.warning(
                f"Failed to parse execution model specification '{execution_spec}': {e}. "
                f"Attempting to continue with fallback parsing."
            )
            raise ValueError(
                f"Invalid execution model specification: '{execution_spec}'. "
                f"Error: {e}. "
                "Expected format: backend:model or backend:model?params. "
                "Example: qwen-oauth:qwen3-coder-plus?temperature=0.3"
            ) from e

        execution_backend = execution_backend.strip()
        execution_model = execution_model.strip()

        if not execution_backend or not execution_model:
            raise ValueError(
                f"Incomplete execution model specification: '{execution_spec}'. "
                "Both backend and model must be non-empty. "
                "Example: qwen-oauth:qwen3-coder-plus"
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Parsed hybrid model spec: reasoning={reasoning_backend}:{reasoning_model} (params={reasoning_params}), "
                f"execution={execution_backend}:{execution_model} (params={execution_params})"
            )

        return HybridModelSpec(
            reasoning_backend=reasoning_backend,
            reasoning_model=reasoning_model,
            reasoning_params=reasoning_params,
            execution_backend=execution_backend,
            execution_model=execution_model,
            execution_params=execution_params,
        )
