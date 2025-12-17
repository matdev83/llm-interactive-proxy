from __future__ import annotations

from pydantic import ConfigDict, model_validator

from src.core.interfaces.model_bases import DomainModel


class RoutingConfig(DomainModel):
    """Configuration for routing policies."""

    model_config = ConfigDict(frozen=True)

    disable_backend_ids: bool = False
    disable_backend_names: bool = False
    disable_model_names: bool = False

    @model_validator(mode="after")
    def validate_at_least_one_method_enabled(self) -> RoutingConfig:
        """Ensure at least one routing method remains available."""
        if self.disable_backend_names and self.disable_model_names:
            raise ValueError(
                "Invalid routing config: cannot disable both backend names and "
                "model-only routing. At least one routing method must remain available."
            )
        return self
