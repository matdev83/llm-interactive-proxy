"""Domain models for hybrid backend.

This module contains all domain data structures used by the hybrid backend.
Models are pure data structures with no business logic dependencies.
"""

from src.connectors.hybrid_backend.models.injection_decision import (
    InjectionDecision,
)
from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec
from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult
from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText

__all__ = [
    "HybridModelSpec",
    "ReasoningPhaseResult",
    "ReasoningText",
    "InjectionDecision",
]
