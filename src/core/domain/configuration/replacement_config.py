"""Configuration for random model replacement feature."""

from __future__ import annotations

from typing import Any

from src.core.domain.base import ValueObject


class ReplacementConfig(ValueObject):
    """Configuration for random model replacement.

    This configuration controls probabilistic swapping of user-specified
    backend:model pairs with alternative replacement pairs during a session.
    """

    enabled: bool = False
    probability: float = 0.0
    backend_model: str = ""
    turn_count: int = 1

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        """Run post-initialization validation."""
        super().model_post_init(__context)
        self.validate_config()

    def validate_config(self) -> None:
        """Validate configuration parameters.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        if self.enabled:
            if not (0.0 <= self.probability <= 1.0):
                raise ValueError(
                    f"replacement_probability must be between 0.0 and 1.0, got {self.probability}"
                )
            if not self.backend_model:
                raise ValueError(
                    "replacement_backend_model must be provided when enabled"
                )
            if ":" not in self.backend_model:
                raise ValueError(
                    f"replacement_backend_model must be in format 'backend:model', got {self.backend_model}"
                )
            if self.turn_count < 1:
                raise ValueError(
                    f"replacement_turn_count must be at least 1, got {self.turn_count}"
                )

    def parse_backend_model(self) -> tuple[str, str]:
        """Parse backend:model string into components.

        Returns:
            Tuple of (backend, model) strings.

        Raises:
            ValueError: If backend_model format is invalid.
        """
        if ":" not in self.backend_model:
            raise ValueError(
                f"replacement_backend_model must be in format 'backend:model', got {self.backend_model}"
            )
        parts = self.backend_model.split(":", 1)
        return (parts[0], parts[1])
