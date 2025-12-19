"""Hybrid backend package - modular architecture for two-phase reasoning.

This package provides a layered architecture for orchestrating hybrid
two-phase LLM interactions (reasoning → execution).

Public exports:
    - HybridOrchestrator: Main orchestration entry point
    - Models: HybridModelSpec, ReasoningPhaseResult, ReasoningText, InjectionDecision
    - Protocols: All I* protocol interfaces for dependency injection
"""

from src.connectors.hybrid_backend.models import (
    HybridModelSpec,
    InjectionDecision,
    ReasoningPhaseResult,
    ReasoningText,
)
from src.connectors.hybrid_backend.orchestration import HybridOrchestrator
from src.connectors.hybrid_backend.protocols import (
    IHybridOrchestrator,
    IInjectionPolicy,
    IMessageAugmentor,
    IModelSpecParser,
    IParameterApplicator,
    IPhaseExecutor,
    IReasoningMarkupProcessor,
    IResponseBuilder,
    IResponseFilter,
)

__all__ = [
    # Models
    "HybridModelSpec",
    "ReasoningPhaseResult",
    "ReasoningText",
    "InjectionDecision",
    # Orchestrator
    "HybridOrchestrator",
    # Protocols
    "IModelSpecParser",
    "IParameterApplicator",
    "IReasoningMarkupProcessor",
    "IMessageAugmentor",
    "IResponseFilter",
    "IResponseBuilder",
    "IInjectionPolicy",
    "IPhaseExecutor",
    "IHybridOrchestrator",
]
