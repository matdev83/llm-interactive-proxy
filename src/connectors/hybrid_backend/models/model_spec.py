"""Hybrid model specification dataclass."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HybridModelSpec:
    """Specification for a hybrid model configuration.

    This dataclass represents a parsed hybrid model specification string
    in the format: hybrid:[backend:model?params,backend:model?params]

    Attributes:
        reasoning_backend: Backend name for reasoning phase (e.g., "openai", "anthropic")
        reasoning_model: Model name for reasoning phase (e.g., "gpt-4", "claude-3-opus")
        reasoning_params: URI parameters for reasoning phase (parsed from query string)
        execution_backend: Backend name for execution phase (e.g., "openai", "anthropic")
        execution_model: Model name for execution phase (e.g., "gpt-3.5-turbo", "claude-3-sonnet")
        execution_params: URI parameters for execution phase (parsed from query string)
    """

    reasoning_backend: str
    reasoning_model: str
    reasoning_params: dict[str, Any] = field(default_factory=dict)
    execution_backend: str = ""
    execution_model: str = ""
    execution_params: dict[str, Any] = field(default_factory=dict)
