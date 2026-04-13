from __future__ import annotations

from src.core.config.models.request_processing_unification import (
    RequestProcessingPromotionRequirementsConfig,
)
from src.core.services.promotion_guardrail_evaluator import (
    PromotionEvidenceSnapshot,
    PromotionGuardrailEvaluator,
)


def test_all_checks_pass_with_default_requirements() -> None:
    ev = PromotionEvidenceSnapshot(
        characterization_tests_pass=True,
        equivalence_tests_pass=True,
        cleanup_checks_pass=True,
        non_stream_p95_latency_delta_pct=0.0,
        stream_ttft_delta_pct=0.0,
        memory_delta_pct=0.0,
    )
    result = PromotionGuardrailEvaluator().evaluate(ev)
    assert result.overall_passed is True
    assert result.promotion_blocked is False
    assert result.rollback_recommended is False
    assert result.diagnostics["overall_passed"] is True


def test_latency_regression_blocks_and_recommends_rollback() -> None:
    req = RequestProcessingPromotionRequirementsConfig(
        require_characterization_tests=False,
        require_equivalence_tests=False,
        require_cleanup_checks=False,
        max_non_stream_p95_latency_delta_pct=5.0,
    )
    ev = PromotionEvidenceSnapshot(
        non_stream_p95_latency_delta_pct=6.0,
        stream_ttft_delta_pct=0.0,
        memory_delta_pct=0.0,
    )
    result = PromotionGuardrailEvaluator().evaluate(ev, requirements=req)
    assert result.overall_passed is False
    assert result.promotion_blocked is True
    assert result.rollback_recommended is True
    names = [c.name for c in result.checks if not c.passed]
    assert "non_stream_p95_latency_delta_pct" in names


def test_missing_evidence_fails_required_boolean_gate() -> None:
    ev = PromotionEvidenceSnapshot(
        characterization_tests_pass=None,
        equivalence_tests_pass=True,
        cleanup_checks_pass=True,
        non_stream_p95_latency_delta_pct=0.0,
        stream_ttft_delta_pct=0.0,
        memory_delta_pct=0.0,
    )
    result = PromotionGuardrailEvaluator().evaluate(ev)
    assert result.overall_passed is False
    failed = [c for c in result.checks if not c.passed]
    assert any(c.name == "characterization_tests" for c in failed)
    assert any(c.detail == "missing_evidence" for c in failed)


def test_strict_missing_evidence_false_neutralizes_unknowns() -> None:
    ev = PromotionEvidenceSnapshot()
    result = PromotionGuardrailEvaluator().evaluate(ev, strict_missing_evidence=False)
    assert result.overall_passed is True
    assert result.promotion_blocked is False
    assert result.diagnostics["strict_missing_evidence"] is False
    assert all(
        c.detail == "missing_evidence_neutral" or c.detail == "not_required"
        for c in result.checks
    )


def test_optional_boolean_gates_skipped() -> None:
    req = RequestProcessingPromotionRequirementsConfig(
        require_characterization_tests=False,
        require_equivalence_tests=False,
        require_cleanup_checks=False,
    )
    ev = PromotionEvidenceSnapshot(
        non_stream_p95_latency_delta_pct=1.0,
        stream_ttft_delta_pct=1.0,
        memory_delta_pct=1.0,
    )
    result = PromotionGuardrailEvaluator().evaluate(ev, requirements=req)
    assert result.overall_passed is True
