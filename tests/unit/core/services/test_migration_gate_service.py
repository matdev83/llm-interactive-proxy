from typing import cast

from pydantic.types import JsonValue
from src.core.config.models.request_processing_unification import (
    RequestProcessingPromotionRequirementsConfig,
    RequestProcessingUnificationConfig,
)
from src.core.services.migration_gate_service import MigrationGateService


def test_select_core_path_default_uses_canonical() -> None:
    service = MigrationGateService()

    decision = service.select_core_path(requested_stream=True)

    assert decision.canonical_path_used is True
    assert decision.selected_path == "canonical_core"
    assert decision.migration_stage == "canonical_runtime"


def test_select_core_path_emits_diagnostics_when_enabled() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            emit_path_selection_metadata=True,
        )
    )

    decision = service.select_core_path(requested_stream=False)
    diagnostics = service.build_diagnostics(decision)

    assert decision.forced_backend_stream is False
    assert decision.connector_stream_first_used is False
    assert decision.canonical_path_used is True
    assert diagnostics["migration_stage"] == "canonical_runtime"
    assert diagnostics["canonical_path_used"] is True
    assert diagnostics["feature_canonical_used"] is False
    assert diagnostics["connector_stream_first_used"] is False
    assert diagnostics["forced_backend_stream"] is False
    assert diagnostics["retire_legacy_dual_path"] is False
    assert "legacy_streaming_client_blocking_envelope" not in diagnostics
    assert "promotion_guardrails" in diagnostics
    promotion_guardrails = cast(
        dict[str, JsonValue], diagnostics["promotion_guardrails"]
    )
    assert promotion_guardrails["strict_missing_evidence"] is True
    assert promotion_guardrails["overall_passed"] is False
    assert promotion_guardrails["promotion_blocked"] is True


def test_connector_stream_first_applies_when_backend_in_cohort_even_if_enable_false() -> (
    None
):
    """connector_stream_first is honored; enable_core_canonical_path is not a path toggle."""
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=False,
            connector_stream_first={"acme": True},
        )
    )
    decision = service.select_core_path(
        requested_stream=False,
        backend_name="acme",
    )
    assert decision.canonical_path_used is True
    assert decision.connector_stream_first_used is True
    assert decision.forced_backend_stream is True


def test_connector_stream_first_cohort_true_for_non_streaming() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            emit_path_selection_metadata=True,
            connector_stream_first={"acme": True},
        )
    )
    decision = service.select_core_path(
        requested_stream=False,
        backend_name="acme",
    )
    assert decision.connector_stream_first_used is True
    assert decision.forced_backend_stream is True
    diagnostics = service.build_diagnostics(decision)
    assert diagnostics["forced_backend_stream"] is True
    assert diagnostics["connector_stream_first_used"] is True


def test_connector_stream_first_cohort_false_opt_out_for_non_streaming() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            connector_stream_first={"acme": False},
        )
    )
    decision = service.select_core_path(
        requested_stream=False,
        backend_name="acme",
    )
    assert decision.connector_stream_first_used is False
    assert decision.forced_backend_stream is False


def test_canonical_always_forces_backend_stream_even_when_client_streams() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            connector_stream_first={"acme": True},
        )
    )
    decision = service.select_core_path(
        requested_stream=True,
        backend_name="acme",
    )
    assert decision.connector_stream_first_used is False
    assert decision.forced_backend_stream is True


def test_canonical_unknown_backend_does_not_force_backend_stream() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            connector_stream_first={"acme": True},
        )
    )
    decision = service.select_core_path(
        requested_stream=False,
        backend_name="other",
    )
    assert decision.connector_stream_first_used is False
    assert decision.forced_backend_stream is False


def test_retire_legacy_dual_path_surfaces_on_canonical_decision() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            retire_legacy_dual_path=True,
        )
    )
    decision = service.select_core_path(requested_stream=True)
    assert decision.canonical_path_used is True
    assert decision.retire_legacy_dual_path is True


def test_retire_legacy_dual_path_included_in_diagnostics_when_emit_enabled() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            emit_path_selection_metadata=True,
            retire_legacy_dual_path=True,
        )
    )
    decision = service.select_core_path(requested_stream=False)
    diagnostics = service.build_diagnostics(decision)
    assert diagnostics["retire_legacy_dual_path"] is True


def test_retire_legacy_dual_path_snapshot_on_legacy_path() -> None:
    """Retirement gate cannot be enabled while canonical core path flag is disabled."""
    try:
        RequestProcessingUnificationConfig(
            enable_core_canonical_path=False,
            retire_legacy_dual_path=True,
        )
    except ValueError as exc:
        assert "retire_legacy_dual_path" in str(exc)
    else:
        raise AssertionError(
            "Expected retire_legacy_dual_path dependency validation to fail"
        )


def test_promotion_requirements_from_config_used_in_diagnostics() -> None:
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            enable_core_canonical_path=True,
            emit_path_selection_metadata=True,
            promotion_requirements=RequestProcessingPromotionRequirementsConfig(
                require_characterization_tests=False,
                require_equivalence_tests=False,
                require_cleanup_checks=False,
                max_non_stream_p95_latency_delta_pct=7.5,
            ),
        )
    )
    decision = service.select_core_path(requested_stream=False)
    diag = service.build_diagnostics(decision)
    promotion_guardrails = cast(dict[str, JsonValue], diag["promotion_guardrails"])
    thresholds = cast(dict[str, JsonValue], promotion_guardrails["thresholds"])
    assert thresholds["require_characterization_tests"] is False
    assert thresholds["max_non_stream_p95_latency_delta_pct"] == 7.5
    assert promotion_guardrails["strict_missing_evidence"] is True
    assert promotion_guardrails["overall_passed"] is False


def test_build_diagnostics_promotion_reflects_missing_evidence_under_defaults() -> None:
    """Emitted diagnostics must not imply promotion readiness without evidence."""
    service = MigrationGateService(
        config=RequestProcessingUnificationConfig(
            emit_path_selection_metadata=True,
        )
    )
    decision = service.select_core_path(requested_stream=False)
    promo = cast(dict[str, JsonValue], service.build_diagnostics(decision)[
        "promotion_guardrails"
    ])
    assert promo["strict_missing_evidence"] is True
    assert promo["overall_passed"] is False
    assert promo["promotion_blocked"] is True
    checks = cast(list[dict[str, JsonValue]], promo["checks"])
    details = {c["name"]: c["detail"] for c in checks}
    assert details["characterization_tests"] == "missing_evidence"
    assert details["non_stream_p95_latency_delta_pct"] == "missing_evidence"
