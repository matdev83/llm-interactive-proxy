"""Backend target canonical contract.

This module defines the BackendTarget value object which represents
a canonical backend target with backend, model, and URI parameters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic.types import JsonValue

from src.core.domain.base import ValueObject

if TYPE_CHECKING:
    from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget


class BackendTarget(ValueObject):
    """Canonical contract for backend target resolution.

    Represents a resolved backend target with backend name, model name,
    and URI parameters. This is the canonical contract used for cross-layer
    data exchange between routing/target resolution and completion orchestration.

    Attributes:
        backend: The resolved backend name (e.g., "openai", "anthropic", "gemini")
        model: The resolved model name (e.g., "gpt-4", "claude-3-5-sonnet")
        uri_params: URI parameters extracted from the model string.
            Values must be JSON-serializable (JsonValue).
    """

    backend: str
    model: str
    uri_params: dict[str, JsonValue]

    @classmethod
    def from_resolved_target(cls, resolved: ResolvedTarget) -> BackendTarget:
        """Create BackendTarget from ResolvedTarget (compatibility conversion).

        Args:
            resolved: ResolvedTarget NamedTuple instance

        Returns:
            BackendTarget value object with same data
        """
        return cls(
            backend=resolved.backend,
            model=resolved.model,
            uri_params=resolved.uri_params,
        )

    def to_resolved_target(self) -> ResolvedTarget:
        """Convert BackendTarget to ResolvedTarget (compatibility conversion).

        Returns:
            ResolvedTarget NamedTuple with same data
        """
        from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

        return ResolvedTarget(
            backend=self.backend,
            model=self.model,
            uri_params=self.uri_params,
        )
