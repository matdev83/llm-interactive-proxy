"""Configuration for auxiliary request routing.

This module defines configuration for routing auxiliary requests (title generation,
summarization, etc.) to alternative backends to reduce rate limiting pressure
on the primary backend.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator
from typing_extensions import Self

from src.core.interfaces.model_bases import DomainModel


class AuxiliaryRoutingConfig(DomainModel):
    """Configuration for auxiliary request routing.

    Auxiliary requests (title generation, summarization) can be routed to
    a different, more tolerant backend to avoid rate limiting on the primary
    backend used for main conversation requests.

    Example config:
        auxiliary_routing:
          enabled: true
          backend: "openrouter"
          model: "google/gemini-flash-1.5"
          detection_patterns:
            - "The following is the text to summarize"
            - "Generate a title"
          max_message_count: 3
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Whether auxiliary request routing is enabled",
    )
    backend: str | None = Field(
        default=None,
        description="Backend to use for auxiliary requests (e.g., 'openrouter', 'gemini-flash')",
    )
    model: str | None = Field(
        default=None,
        description="Model to use on the auxiliary backend (optional, uses backend default if not set)",
    )
    detection_patterns: list[str] = Field(
        default_factory=lambda: [
            r"The following is the text to summarize",
            r"Generate a (?:short |brief )?(?:title|summary|heading)",
            r"Summarize (?:the|this|my) (?:conversation|text|content|task)",
            r"Create a (?:title|heading) for",
            r"Generate a title for the (?:session|conversation)",
            r"Provide a summary of (?:the|this|my) (?:task|conversation|session)",
        ],
        description="Regex patterns to detect auxiliary requests in message content",
    )
    max_message_count: int = Field(
        default=3,
        description="Maximum message count for a request to be considered auxiliary (auxiliary requests typically have few messages)",
    )

    @model_validator(mode="after")
    def validate_target_configured_if_enabled(self) -> Self:
        """Ensure a valid routing target is configured if enabled."""
        if self.enabled:
            # Must have either a backend explicitly set, or a model with FQN
            has_backend = bool(self.backend)
            has_fqn_model = bool(self.model and ":" in self.model)
            if not has_backend and not has_fqn_model:
                raise ValueError(
                    "Auxiliary routing is enabled but no target is configured. "
                    "Please provide --auxiliary-routing-model <backend>:<model> "
                    "or configure a backend explicitly."
                )
        return self
