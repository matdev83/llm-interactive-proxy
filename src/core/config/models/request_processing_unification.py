from __future__ import annotations

from pydantic import Field, model_validator

from src.core.interfaces.model_bases import DomainModel


class RequestProcessingPromotionRequirementsConfig(DomainModel):
    """Promotion guardrails for request-processing migration evidence checks."""

    require_characterization_tests: bool = True
    require_equivalence_tests: bool = True
    max_non_stream_p95_latency_delta_pct: float = Field(default=10.0, ge=0.0)
    max_stream_ttft_delta_pct: float = Field(default=10.0, ge=0.0)
    max_memory_delta_pct: float = Field(default=10.0, ge=0.0)
    require_cleanup_checks: bool = True


class RequestProcessingUnificationConfig(DomainModel):
    """Request-processing migration settings (canonical path is always selected at runtime)."""

    enable_core_canonical_path: bool = True
    enable_canonical_features: bool = False
    connector_stream_first: dict[str, bool] = Field(default_factory=dict)
    retire_legacy_dual_path: bool = False
    emit_path_selection_metadata: bool = False
    legacy_streaming_client_blocking_envelope: bool = False
    promotion_requirements: RequestProcessingPromotionRequirementsConfig = Field(
        default_factory=RequestProcessingPromotionRequirementsConfig
    )

    # Empty stream recovery tuning (operational flexibility)
    empty_stream_recovery_prompt: str = Field(
        default="The previous response was empty, please try again.",
        description="Recovery prompt appended to retry requests when stream produces no content",
    )
    max_empty_stream_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Maximum number of empty stream retry attempts before failing",
    )

    @model_validator(mode="after")
    def _validate_gate_dependencies(self) -> RequestProcessingUnificationConfig:
        """Prevent retirement from being enabled without the canonical core path."""
        if self.retire_legacy_dual_path and not self.enable_core_canonical_path:
            msg = "retire_legacy_dual_path requires enable_core_canonical_path=true"
            raise ValueError(msg)
        return self
