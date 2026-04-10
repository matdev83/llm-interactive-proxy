from __future__ import annotations

from src.core.domain.composite_routing import (
    CompositeBranchOutcomeCategory,
    CompositeBranchRecord,
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeRoutePlan,
    CompositeRoutingAttemptContext,
    CompositeRoutingErrorCode,
    CompositeRoutingFailure,
    CompositeRoutingInput,
    CompositeRoutingSuccess,
    CompositeValidationErrorCode,
    CompositeValidationErrorEnvelope,
    RoutingSurface,
)
from src.core.domain.configuration.failure_handling_config import (
    DEFAULT_FAILURE_HANDLING_CONFIG,
)


def test_composite_route_plan_serialization_is_typed_and_stable() -> None:
    leaf = CompositeLeafSelector(
        raw_selector="openai:gpt-4",
        normalized_selector="openai:gpt-4",
        weight_annotation=None,
        uri_params={},
    )
    plan = CompositeRoutePlan(
        source_selector="openai:gpt-4",
        normalized_selector="openai:gpt-4",
        root_node=CompositeLeafNode(leaf_selector=leaf),
    )

    dumped = plan.model_dump()
    assert dumped["root_node"]["kind"] == "leaf"
    assert dumped["root_node"]["leaf_selector"]["normalized_selector"] == "openai:gpt-4"
    assert plan.grammar_version.startswith("composite-routing-v")


def test_validation_error_envelope_truncates_operator_facing_fields() -> None:
    envelope = CompositeValidationErrorEnvelope(
        code=CompositeValidationErrorCode.INVALID_WEIGHT,
        message="x" * 1024,
        selector_echo="openai:gpt-4?" + ("y" * 1024),
    )

    assert len(envelope.message) <= 256
    assert len(envelope.selector_echo) <= 512
    assert "truncated" in envelope.message
    assert "truncated" in envelope.selector_echo


def test_attempt_context_uses_existing_hop_default_when_not_overridden() -> None:
    context = CompositeRoutingAttemptContext.create(surface=RoutingSurface.MAIN)
    assert context.max_hops == DEFAULT_FAILURE_HANDLING_CONFIG.max_failover_hops
    assert context.hop_count == 0
    assert context.exhaustion_reason is None


def test_attempt_context_tracks_shared_hop_budget_and_exhaustion_reason() -> None:
    context = CompositeRoutingAttemptContext.create(
        surface=RoutingSurface.AUXILIARY,
        configured_max_hops=2,
    )

    assert context.consume_hop(reason_code="validation_rejected") is True
    assert context.hop_count == 1
    assert context.is_exhausted is False

    assert context.consume_hop(reason_code="ineligible") is True
    assert context.hop_count == 2
    assert context.is_exhausted is True
    assert context.exhaustion_reason == "ineligible"

    assert context.consume_hop(reason_code="runtime_failed") is False
    assert context.hop_count == 2
    assert context.exhaustion_reason == "ineligible"


def test_attempt_context_bounds_branch_history_for_diagnostics() -> None:
    context = CompositeRoutingAttemptContext.create(
        surface=RoutingSurface.QUALITY_VERIFIER,
        configured_max_hops=5,
        history_limit=2,
    )

    context.record_branch(
        CompositeBranchRecord(
            selector_fragment="openai:gpt-4",
            outcome_category=CompositeBranchOutcomeCategory.SELECTED,
            backend="openai",
            model="gpt-4",
            reason_code=None,
        )
    )
    context.record_branch(
        CompositeBranchRecord(
            selector_fragment="anthropic:claude-3-5-sonnet",
            outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE,
            backend=None,
            model=None,
            reason_code="temporarily_unavailable",
        )
    )
    context.record_branch(
        CompositeBranchRecord(
            selector_fragment="openrouter:gpt-4o-mini",
            outcome_category=CompositeBranchOutcomeCategory.RUNTIME_FAILED,
            backend="openrouter",
            model="gpt-4o-mini",
            reason_code="rate_limited",
        )
    )

    assert len(context.branch_history) == 2
    assert [entry.selector_fragment for entry in context.branch_history] == [
        "anthropic:claude-3-5-sonnet",
        "openrouter:gpt-4o-mini",
    ]
    assert context.branch_history_omitted == 1


def test_surface_aware_input_and_outcome_envelopes_are_typed() -> None:
    request_input = CompositeRoutingInput(
        selector="openai:gpt-4",
        surface=RoutingSurface.REPLACEMENT_BRIDGE,
        require_explicit_backend=True,
        configured_max_hops=3,
    )

    context = CompositeRoutingAttemptContext.create(
        surface=request_input.surface,
        configured_max_hops=request_input.configured_max_hops,
    )

    success = CompositeRoutingSuccess(
        selected_selector="openai:gpt-4",
        selected_backend="openai",
        selected_model="gpt-4",
        attempt_context=context,
    )
    failure = CompositeRoutingFailure(
        error_code=CompositeRoutingErrorCode.ROUTING_VALIDATION_FAILED,
        message="selector failed validation",
        attempt_context=context,
    )

    assert request_input.surface is RoutingSurface.REPLACEMENT_BRIDGE
    assert success.kind == "selected_target"
    assert failure.kind == "routing_error"
