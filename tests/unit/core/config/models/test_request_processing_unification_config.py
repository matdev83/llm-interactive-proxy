from src.core.config.models.request_processing_unification import (
    RequestProcessingPromotionRequirementsConfig,
    RequestProcessingUnificationConfig,
)


def test_request_processing_unification_defaults_are_safe() -> None:
    config = RequestProcessingUnificationConfig()

    assert config.enable_core_canonical_path is True
    assert config.enable_canonical_features is False
    assert config.retire_legacy_dual_path is False
    assert config.emit_path_selection_metadata is False
    assert config.connector_stream_first == {}
    assert config.legacy_streaming_client_blocking_envelope is False


def test_promotion_requirements_reject_negative_thresholds() -> None:
    try:
        RequestProcessingPromotionRequirementsConfig(
            max_non_stream_p95_latency_delta_pct=-1.0,
        )
    except ValueError as exc:
        assert "max_non_stream_p95_latency_delta_pct" in str(exc)
    else:
        raise AssertionError("Expected negative threshold to be rejected")


def test_retire_legacy_dual_path_requires_canonical_core_path() -> None:
    try:
        RequestProcessingUnificationConfig(
            enable_core_canonical_path=False,
            retire_legacy_dual_path=True,
        )
    except ValueError as exc:
        assert "retire_legacy_dual_path" in str(exc)
    else:
        raise AssertionError(
            "Expected retire_legacy_dual_path gate dependency to be enforced"
        )
