from __future__ import annotations

from dataclasses import dataclass

from pydantic.types import JsonValue

from src.core.config.app_config import AppConfig
from src.core.config.models.request_processing_unification import (
    RequestProcessingPromotionRequirementsConfig,
    RequestProcessingUnificationConfig,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.configuration_interface import IConfig
from src.core.services.promotion_guardrail_evaluator import (
    PromotionEvidenceSnapshot,
    PromotionGuardrailEvaluator,
)


@dataclass(frozen=True)
class CorePathDecision:
    """Decision snapshot for the manager-level canonical path gate."""

    selected_path: str
    migration_stage: str
    canonical_path_used: bool
    feature_canonical_used: bool
    connector_stream_first_used: bool
    forced_backend_stream: bool
    retire_legacy_dual_path: bool


class MigrationGateService:
    """Read-only runtime gate decisions for request-processing migration stages."""

    def __init__(
        self,
        config: RequestProcessingUnificationConfig | AppConfig | IConfig | None = None,
        promotion_guardrail_evaluator: PromotionGuardrailEvaluator | None = None,
    ) -> None:
        self._config = self._extract_gate_config(config)
        self._promotion_guardrail_evaluator = (
            promotion_guardrail_evaluator
            or PromotionGuardrailEvaluator(
                requirements=self._config.promotion_requirements
            )
        )

    @classmethod
    def from_flags(
        cls,
        *,
        enable_core_canonical_path: bool,
        emit_path_selection_metadata: bool,
        connector_stream_first: dict[str, bool] | None = None,
        retire_legacy_dual_path: bool = False,
        legacy_streaming_client_blocking_envelope: bool = False,
        enable_canonical_features: bool = False,
        promotion_requirements: (
            RequestProcessingPromotionRequirementsConfig | None
        ) = None,
    ) -> MigrationGateService:
        return cls(
            config=RequestProcessingUnificationConfig(
                enable_core_canonical_path=enable_core_canonical_path,
                enable_canonical_features=enable_canonical_features,
                emit_path_selection_metadata=emit_path_selection_metadata,
                connector_stream_first=dict(connector_stream_first or {}),
                retire_legacy_dual_path=retire_legacy_dual_path,
                legacy_streaming_client_blocking_envelope=legacy_streaming_client_blocking_envelope,
                promotion_requirements=promotion_requirements
                or RequestProcessingPromotionRequirementsConfig(),
            )
        )

    @staticmethod
    def _extract_gate_config(
        config: RequestProcessingUnificationConfig | AppConfig | IConfig | None,
    ) -> RequestProcessingUnificationConfig:
        if isinstance(config, RequestProcessingUnificationConfig):
            return config
        if isinstance(config, AppConfig):
            gate_cfg = getattr(config, "request_processing_unification", None)
            if isinstance(gate_cfg, RequestProcessingUnificationConfig):
                return gate_cfg
            if isinstance(gate_cfg, dict):
                return RequestProcessingUnificationConfig.model_validate(gate_cfg)
            return RequestProcessingUnificationConfig()
        if config is None:
            return RequestProcessingUnificationConfig()

        gate_config = config.get("request_processing_unification", None)
        if isinstance(gate_config, RequestProcessingUnificationConfig):
            return gate_config
        if isinstance(gate_config, dict):
            return RequestProcessingUnificationConfig.model_validate(gate_config)
        return RequestProcessingUnificationConfig()

    def select_core_path(
        self,
        requested_stream: bool,
        *,
        backend_name: str | None = None,
    ) -> CorePathDecision:
        retire = self._config.retire_legacy_dual_path
        # Single canonical runtime path; enable_core_canonical_path remains in config for
        # compatibility and retirement validation only.

        if requested_stream:
            return CorePathDecision(
                selected_path="canonical_core",
                migration_stage="canonical_runtime",
                canonical_path_used=True,
                feature_canonical_used=self._config.enable_canonical_features,
                connector_stream_first_used=False,
                forced_backend_stream=True,
                retire_legacy_dual_path=retire,
            )

        cohort = self._config.connector_stream_first
        cohort_value: bool | None
        if backend_name is not None and backend_name in cohort:
            cohort_value = cohort[backend_name]
        else:
            cohort_value = None

        if cohort_value is True:
            return CorePathDecision(
                selected_path="canonical_core",
                migration_stage="canonical_runtime",
                canonical_path_used=True,
                feature_canonical_used=self._config.enable_canonical_features,
                connector_stream_first_used=True,
                forced_backend_stream=True,
                retire_legacy_dual_path=retire,
            )
        if cohort_value is False:
            return CorePathDecision(
                selected_path="canonical_core",
                migration_stage="canonical_runtime",
                canonical_path_used=True,
                feature_canonical_used=self._config.enable_canonical_features,
                connector_stream_first_used=False,
                forced_backend_stream=False,
                retire_legacy_dual_path=retire,
            )

        return CorePathDecision(
            selected_path="canonical_core",
            migration_stage="canonical_runtime",
            canonical_path_used=True,
            feature_canonical_used=self._config.enable_canonical_features,
            connector_stream_first_used=False,
            forced_backend_stream=False,
            retire_legacy_dual_path=retire,
        )

    def build_diagnostics(self, decision: CorePathDecision) -> dict[str, JsonValue]:
        if not self._config.emit_path_selection_metadata:
            return {}
        out: dict[str, JsonValue] = {
            "migration_stage": decision.migration_stage,
            "selected_processing_path": decision.selected_path,
            "canonical_path_used": decision.canonical_path_used,
            "feature_canonical_used": decision.feature_canonical_used,
            "connector_stream_first_used": decision.connector_stream_first_used,
            "forced_backend_stream": decision.forced_backend_stream,
            "retire_legacy_dual_path": decision.retire_legacy_dual_path,
        }
        promo = self._promotion_guardrail_evaluator.evaluate(
            PromotionEvidenceSnapshot(),
            requirements=self._config.promotion_requirements,
        )
        out["promotion_guardrails"] = promo.diagnostics
        return out

    def apply_diagnostics(
        self,
        context: RequestContext,
        *,
        decision: CorePathDecision,
        requested_stream: bool,
    ) -> None:
        diagnostics = self.build_diagnostics(decision)
        if not diagnostics:
            return
        diagnostics["requested_stream_mode"] = requested_stream
        context.extensions.update(diagnostics)
