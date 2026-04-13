"""Evidence-driven promotion guardrails for request-processing migration (Wave 7.4 / 8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic.types import JsonValue

from src.core.config.models.request_processing_unification import (
    RequestProcessingPromotionRequirementsConfig,
)


@dataclass(frozen=True)
class PromotionEvidenceSnapshot:
    """Observed evidence compared against :class:`RequestProcessingPromotionRequirementsConfig`."""

    characterization_tests_pass: bool | None = None
    equivalence_tests_pass: bool | None = None
    non_stream_p95_latency_delta_pct: float | None = None
    stream_ttft_delta_pct: float | None = None
    memory_delta_pct: float | None = None
    cleanup_checks_pass: bool | None = None


@dataclass(frozen=True)
class GuardrailCheckResult:
    """Single guardrail outcome."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromotionGuardrailEvaluation:
    """Aggregated promotion decision with explicit rollback guidance."""

    checks: tuple[GuardrailCheckResult, ...]
    overall_passed: bool
    rollback_recommended: bool
    promotion_blocked: bool
    diagnostics: dict[str, JsonValue] = field(default_factory=dict)


class PromotionGuardrailEvaluator:
    """Evaluate migration promotion evidence against configured thresholds."""

    def __init__(
        self,
        requirements: RequestProcessingPromotionRequirementsConfig | None = None,
    ) -> None:
        self._requirements = (
            requirements or RequestProcessingPromotionRequirementsConfig()
        )

    def evaluate(
        self,
        evidence: PromotionEvidenceSnapshot,
        *,
        requirements: RequestProcessingPromotionRequirementsConfig | None = None,
        strict_missing_evidence: bool = True,
    ) -> PromotionGuardrailEvaluation:
        req = requirements or self._requirements
        checks: list[GuardrailCheckResult] = []

        def _bool_gate(
            name: str,
            required: bool,
            value: bool | None,
        ) -> GuardrailCheckResult:
            if not required:
                return GuardrailCheckResult(
                    name=name,
                    passed=True,
                    detail="not_required",
                )
            if value is None:
                if not strict_missing_evidence:
                    return GuardrailCheckResult(
                        name=name,
                        passed=True,
                        detail="missing_evidence_neutral",
                    )
                return GuardrailCheckResult(
                    name=name,
                    passed=False,
                    detail="missing_evidence",
                )
            return GuardrailCheckResult(
                name=name,
                passed=bool(value),
                detail="ok" if value else "failed",
            )

        checks.append(
            _bool_gate(
                "characterization_tests",
                req.require_characterization_tests,
                evidence.characterization_tests_pass,
            )
        )
        checks.append(
            _bool_gate(
                "equivalence_tests",
                req.require_equivalence_tests,
                evidence.equivalence_tests_pass,
            )
        )
        checks.append(
            _bool_gate(
                "cleanup_checks",
                req.require_cleanup_checks,
                evidence.cleanup_checks_pass,
            )
        )

        def _delta_gate(
            name: str,
            observed: float | None,
            max_allowed: float,
        ) -> GuardrailCheckResult:
            if observed is None:
                if not strict_missing_evidence:
                    return GuardrailCheckResult(
                        name=name,
                        passed=True,
                        detail="missing_evidence_neutral",
                    )
                return GuardrailCheckResult(
                    name=name,
                    passed=False,
                    detail="missing_evidence",
                )
            if observed <= max_allowed:
                return GuardrailCheckResult(
                    name=name,
                    passed=True,
                    detail=f"delta={observed:.4g} max={max_allowed:.4g}",
                )
            return GuardrailCheckResult(
                name=name,
                passed=False,
                detail=f"delta={observed:.4g} exceeds max={max_allowed:.4g}",
            )

        checks.append(
            _delta_gate(
                "non_stream_p95_latency_delta_pct",
                evidence.non_stream_p95_latency_delta_pct,
                req.max_non_stream_p95_latency_delta_pct,
            )
        )
        checks.append(
            _delta_gate(
                "stream_ttft_delta_pct",
                evidence.stream_ttft_delta_pct,
                req.max_stream_ttft_delta_pct,
            )
        )
        checks.append(
            _delta_gate(
                "memory_delta_pct",
                evidence.memory_delta_pct,
                req.max_memory_delta_pct,
            )
        )

        tup = tuple(checks)
        overall = all(c.passed for c in tup)
        blocked = not overall
        rollback = blocked

        diagnostics: dict[str, JsonValue] = {
            "strict_missing_evidence": strict_missing_evidence,
            "overall_passed": overall,
            "promotion_blocked": blocked,
            "rollback_recommended": rollback,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                }
                for c in tup
            ],
            "thresholds": {
                "max_non_stream_p95_latency_delta_pct": req.max_non_stream_p95_latency_delta_pct,
                "max_stream_ttft_delta_pct": req.max_stream_ttft_delta_pct,
                "max_memory_delta_pct": req.max_memory_delta_pct,
                "require_characterization_tests": req.require_characterization_tests,
                "require_equivalence_tests": req.require_equivalence_tests,
                "require_cleanup_checks": req.require_cleanup_checks,
            },
        }

        return PromotionGuardrailEvaluation(
            checks=tup,
            overall_passed=overall,
            rollback_recommended=rollback,
            promotion_blocked=blocked,
            diagnostics=diagnostics,
        )
