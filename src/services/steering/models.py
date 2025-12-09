"""Data models for the unified steering framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SteeringResult:
    """Outcome of a steering policy evaluation.

    Attributes:
        message: Steering message to return to the agent
        should_block: Whether to swallow the tool call (True) or allow it (False)
        policy_name: Name of the policy that produced this result
        severity: Optional severity/level indicator (e.g., "warning", "error")
        metadata: Additional context for telemetry/logging
    """

    message: str
    should_block: bool = True
    policy_name: str = ""
    severity: str = "warning"
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["SteeringResult"]
