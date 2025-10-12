"""
Pydantic models for usage statistics.

This module defines the data structures for usage statistics returned by the
UsageTrackingService, replacing manual dictionary construction with type-safe
Pydantic models.
"""

from typing import Any

from pydantic import BaseModel, Field


class ModelUsageStats(BaseModel):
    """Statistics for a specific model's usage."""

    total_tokens: int = Field(ge=0, description="Total tokens used by this model")
    prompt_tokens: int = Field(ge=0, description="Prompt tokens used by this model")
    completion_tokens: int = Field(
        ge=0, description="Completion tokens used by this model"
    )
    cost: float = Field(ge=0.0, description="Total cost for this model")
    requests: int = Field(ge=0, description="Number of requests made to this model")


class UsageStatsResponse(BaseModel):
    """Response containing usage statistics grouped by model."""

    stats: dict[str, ModelUsageStats] = Field(
        default_factory=dict, description="Usage statistics grouped by model name"
    )

    def model_dump(self, **kwargs) -> dict[str, dict[str, Any]]:
        """
        Convert to dictionary format expected by existing API consumers.

        Returns the stats dictionary directly to maintain backward compatibility
        with existing code that expects the format:
        {
            "model_name": {
                "total_tokens": int,
                "prompt_tokens": int,
                "completion_tokens": int,
                "cost": float,
                "requests": int
            }
        }
        """
        return {
            model_name: model_stats.model_dump(**kwargs)
            for model_name, model_stats in self.stats.items()
        }

    def __eq__(self, other) -> bool:
        """Enable comparison with dictionaries for backward compatibility."""
        if isinstance(other, dict):
            return self.model_dump() == other
        return super().__eq__(other)

    def __getitem__(self, key: str) -> ModelUsageStats:
        """Allow dictionary-style access for backward compatibility."""
        return self.stats[key]

    def __setitem__(self, key: str, value: ModelUsageStats | dict) -> None:
        """
        Allow dictionary-style assignment with validation for backward compatibility.

        If the value is a dictionary, it will be validated and converted into a
        ModelUsageStats instance.
        """
        if isinstance(value, ModelUsageStats):
            self.stats[key] = value
        else:
            try:
                self.stats[key] = ModelUsageStats.model_validate(value)
            except Exception as e:
                raise ValueError(
                    f"Failed to validate usage stats for model '{key}': {e}"
                ) from e

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator for backward compatibility."""
        return key in self.stats

    def get(
        self, key: str, default: ModelUsageStats | None = None
    ) -> ModelUsageStats | None:
        """Dictionary-style get method for backward compatibility."""
        return self.stats.get(key, default)

    def items(self):
        """Dictionary-style items() method for backward compatibility."""
        return self.stats.items()

    def keys(self):
        """Dictionary-style keys() method for backward compatibility."""
        return self.stats.keys()

    def values(self):
        """Dictionary-style values() method for backward compatibility."""
        return self.stats.values()
