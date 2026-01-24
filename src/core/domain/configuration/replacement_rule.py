"""Replacement rule models for conditional model replacement feature."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplacementRule:
    """Represents a conditional replacement rule.

    A replacement rule specifies when to replace models (from_pattern) and
    what to replace them with (to_backend:to_model).

    Attributes:
        from_pattern: Pattern to match against original models. Can be:
            - "*" - matches all models
            - "model-name" - partial match on model name (substring)
            - "backend:model" - exact match on fully qualified identifier
        to_backend: Target backend to use for replacement (always required)
        to_model: Target model to use for replacement (always required)
    """

    from_pattern: str
    to_backend: str
    to_model: str

    def matches(self, backend: str, model: str) -> bool:
        """Check if this rule matches the given backend:model pair.

        Args:
            backend: The backend identifier
            model: The model identifier

        Returns:
            True if this rule matches the given backend:model, False otherwise
        """
        if self.from_pattern == "*":
            return True

        if ":" in self.from_pattern:
            # Fully qualified match: "backend:model"
            return f"{backend}:{model}" == self.from_pattern
        else:
            # Partial model name match: "model-name"
            return self.from_pattern in model

    def __str__(self) -> str:
        """Return string representation of the rule."""
        return f"{self.from_pattern}={self.to_backend}:{self.to_model}"
