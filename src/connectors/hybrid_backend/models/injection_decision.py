"""Injection decision dataclass."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionDecision:
    """Encapsulates the result of injection policy evaluation.

    This dataclass represents the decision made by the InjectionPolicy
    service about whether reasoning should be injected into the execution
    phase. It includes both the decision and metadata explaining why.

    Attributes:
        should_inject: Whether reasoning should be injected for this request
        reason: Human-readable explanation of the decision (e.g., "first turn forced",
            "probability sample", "backoff active")
        is_first_turn: Whether this is the first user turn in the conversation
        probability_used: The probability value that was evaluated (0.0-1.0)
        backoff_remaining: Current backoff turns remaining after this decision (Req 8.3)
    """

    should_inject: bool
    reason: str
    is_first_turn: bool = False
    probability_used: float = 1.0
    backoff_remaining: int = 0
