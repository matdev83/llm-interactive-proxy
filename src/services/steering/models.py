"""Data models for the unified steering framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class SteeringRuleTriggers(BaseModel):
    """Triggers for a steering rule."""

    tool_names: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)


class SteeringRuleRateLimit(BaseModel):
    """Rate limit configuration for a steering rule."""

    calls_per_window: int = 1
    window_seconds: int = 60


class SteeringRule(BaseModel):
    """Definition of a configurable steering rule."""

    name: str
    message: str
    enabled: bool = True
    priority: int = 50
    triggers: SteeringRuleTriggers = Field(default_factory=SteeringRuleTriggers)
    rate_limit: SteeringRuleRateLimit = Field(default_factory=SteeringRuleRateLimit)


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
