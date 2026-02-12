from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.core.interfaces.model_bases import DomainModel


class RoutingConfig(DomainModel):
    """Configuration for routing policies."""

    model_config = ConfigDict(frozen=True)

    disable_backend_ids: bool = False
    disable_backend_names: bool = False
    disable_model_names: bool = False
    model_only_preference_policy: Literal["round_robin", "cost", "priority"] = (
        "round_robin"
    )
    model_only_model_overrides: dict[
        str, Literal["round_robin", "cost", "priority"]
    ] = Field(default_factory=dict)
    model_only_backend_family_overrides: dict[
        str, Literal["round_robin", "cost", "priority"]
    ] = Field(default_factory=dict)
    model_only_missing_cost: float = 1_000_000.0
    model_only_missing_priority: int = 0
    capability_refresh_interval_seconds: float = 0.0
    capability_refresh_backoff_seconds: float = 30.0

    @field_validator(
        "model_only_model_overrides", "model_only_backend_family_overrides"
    )
    @classmethod
    def validate_override_keys(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, policy in value.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            normalized[normalized_key] = policy
        return normalized

    @field_validator("model_only_missing_cost", mode="after")
    @classmethod
    def validate_missing_cost(cls, value: float) -> float:
        if value < 0:
            raise ValueError("model_only_missing_cost must be >= 0")
        return value

    @field_validator("model_only_missing_priority", mode="after")
    @classmethod
    def validate_missing_priority(cls, value: int) -> int:
        return int(value)

    @field_validator(
        "capability_refresh_interval_seconds", "capability_refresh_backoff_seconds"
    )
    @classmethod
    def validate_refresh_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError("refresh timing values must be >= 0")
        return float(value)

    @model_validator(mode="after")
    def validate_at_least_one_method_enabled(self) -> RoutingConfig:
        """Ensure at least one routing method remains available."""
        if self.disable_backend_names and self.disable_model_names:
            raise ValueError(
                "Invalid routing config: cannot disable both backend names and "
                "model-only routing. At least one routing method must remain available."
            )
        return self
