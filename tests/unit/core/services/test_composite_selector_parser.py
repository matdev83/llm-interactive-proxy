from __future__ import annotations

import pytest
from src.core.domain.composite_routing import (
    CompositeRoutingInput,
    CompositeSelectorValidationError,
    CompositeValidationErrorCode,
    RoutingSurface,
)
from src.core.services.composite_selector_parser import CompositeSelectorParser


def _parse(
    parser: CompositeSelectorParser,
    selector: str,
    *,
    require_explicit_backend: bool = False,
):
    return parser.parse(
        CompositeRoutingInput(
            selector=selector,
            surface=RoutingSurface.MAIN,
            require_explicit_backend=require_explicit_backend,
        )
    )


def test_parse_failover_selector_is_deterministic_and_normalized() -> None:
    parser = CompositeSelectorParser()
    selector = " openai:gpt-4 | anthropic:claude-3-5-sonnet "

    first_plan = _parse(parser, selector)
    second_plan = _parse(parser, selector)

    assert first_plan.model_dump() == second_plan.model_dump()
    assert first_plan.normalized_selector == "openai:gpt-4|anthropic:claude-3-5-sonnet"
    assert first_plan.root_node.kind == "failover_group"
    normalized_children = [
        child.leaf_selector.normalized_selector
        for child in first_plan.root_node.children
    ]
    assert normalized_children == ["openai:gpt-4", "anthropic:claude-3-5-sonnet"]


def test_parse_weighted_selector_applies_default_and_explicit_weights() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(parser, "[weight=3]openai:gpt-4^anthropic:claude-3-haiku")

    assert plan.root_node.kind == "weighted_group"
    weights = [
        child.leaf_selector.weight_annotation for child in plan.root_node.children
    ]
    assert weights == [3, 1]


def test_parse_rejects_mixed_operators() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "openai:gpt-4|anthropic:claude-3^openrouter:gpt-4o-mini")

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_weighted_selector_rejects_pipe_anywhere_in_branch_text() -> None:
    parser = CompositeSelectorParser()
    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(
            parser,
            "[weight=3]openai:gpt-4^"
            "[weight=1]anthropic:claude-3-5-sonnet?note=foo|bar",
        )

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_failover_selector_rejects_caret_anywhere_in_branch_text() -> None:
    parser = CompositeSelectorParser()
    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(
            parser,
            "openai:gpt-4|anthropic:claude-3-5-sonnet?note=foo^bar",
        )

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_real_world_weighted_route_with_explicit_and_default_branch_weights() -> (
    None
):
    parser = CompositeSelectorParser()
    selector = (
        "[weight=3]opencode-go:opencode-go/mimo-v2-pro^"
        "[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=low^"
        "openai-codex:gpt-5.4?reasoning_effort=medium"
    )
    plan = _parse(parser, selector)

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert [leaf.weight_annotation for leaf in leaves] == [3, 2, 1]
    assert leaves[0].uri_params == {}
    assert leaves[0].backend_type == "opencode-go"
    assert leaves[0].model_name == "opencode-go/mimo-v2-pro"
    assert leaves[0].normalized_selector == "opencode-go:opencode-go/mimo-v2-pro"

    assert leaves[1].uri_params == {"reasoning_effort": "low"}
    assert leaves[1].backend_type == "openai-codex"
    assert leaves[1].model_name == "gpt-5.3-codex"
    assert (
        leaves[1].normalized_selector
        == "openai-codex:gpt-5.3-codex?reasoning_effort=low"
    )

    assert leaves[2].uri_params == {"reasoning_effort": "medium"}
    assert leaves[2].backend_type == "openai-codex"
    assert leaves[2].model_name == "gpt-5.4"
    assert (
        leaves[2].normalized_selector == "openai-codex:gpt-5.4?reasoning_effort=medium"
    )

    assert plan.normalized_selector == (
        "[weight=3]opencode-go:opencode-go/mimo-v2-pro^"
        "[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=low^"
        "[weight=1]openai-codex:gpt-5.4?reasoning_effort=medium"
    )


def test_parse_preserves_leaf_local_uri_params_per_branch() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(
        parser,
        "openai:gpt-4?temperature=0.1|anthropic:claude-3-5-sonnet?temperature=0.8&reasoning_effort=high",
    )

    assert plan.root_node.kind == "failover_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert leaves[0].uri_params == {"temperature": "0.1"}
    assert leaves[1].uri_params == {
        "temperature": "0.8",
        "reasoning_effort": "high",
    }


@pytest.mark.parametrize(
    "selector",
    [
        "[weight=0]openai:gpt-4^anthropic:claude-3",
        "[weight=-1]openai:gpt-4^anthropic:claude-3",
        "[weight=abc]openai:gpt-4^anthropic:claude-3",
    ],
)
def test_parse_rejects_invalid_weight_values(selector: str) -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, selector)

    assert exc_info.value.envelope.code == CompositeValidationErrorCode.INVALID_WEIGHT


def test_parse_rejects_malformed_selector_with_empty_branch() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "openai:gpt-4||anthropic:claude-3")

    assert exc_info.value.envelope.code == CompositeValidationErrorCode.SYNTAX_ERROR


def test_parse_rejects_weight_prefix_not_immediately_before_target() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "[weight=2] openai:gpt-4^[weight=1]anthropic:claude-3")

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_validates_leafs_with_surface_aware_constraints() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(
            parser,
            "gpt-4|openai:gpt-4o-mini",
            require_explicit_backend=True,
        )

    assert exc_info.value.envelope.code == CompositeValidationErrorCode.INVALID_LEAF


def test_parse_preserves_existing_vendor_suffix_semantics_for_leaf_selector() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(parser, "openrouter/anthropic/claude-3-haiku:free")

    assert plan.root_node.kind == "leaf"
    leaf = plan.root_node.leaf_selector
    assert leaf.backend_type == ""
    assert leaf.model_name == "openrouter/anthropic/claude-3-haiku:free"


def test_parse_operator_in_query_value_is_treated_as_composite_separator() -> None:
    """Grammar limitation: unencoded ``^`` and ``|`` are always composite operators.

    The flat grammar cannot distinguish an operator inside a query-parameter
    value from a composite separator. URL-encode operator characters
    (``%5E`` for ``^``, ``%7C`` for ``|``) in query values to avoid false
    parsing or mixed-operator validation failures.
    """
    parser = CompositeSelectorParser()

    plan = _parse(parser, "openai:gpt-4?filter=a^b")
    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert leaves[0].uri_params == {"filter": "a"}
    assert leaves[1].model_name == "b"

    plan_pipe = _parse(parser, "openai:gpt-4?filter=a|b")
    assert plan_pipe.root_node.kind == "failover_group"


def test_parse_url_encoded_operator_in_query_value_preserves_value() -> None:
    """URL-encoded operators are treated as literal query content, not splits."""
    parser = CompositeSelectorParser()
    plan = _parse(parser, "openai:gpt-4^anthropic:claude-3?note=x%5Ey")

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert len(leaves) == 2
    assert leaves[1].uri_params == {"note": "x^y"}


@pytest.mark.parametrize(
    "first_annotation",
    ["[first]", "[first=1]", "[first=yes]", "[first=true]"],
)
def test_parse_weighted_selector_accepts_first_annotation_forms(
    first_annotation: str,
) -> None:
    """Test that all accepted [first] annotation forms are parsed correctly."""
    parser = CompositeSelectorParser()
    selector = f"{first_annotation}openai:gpt-4^anthropic:claude-3"

    plan = _parse(parser, selector)

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert len(leaves) == 2
    assert leaves[0].first_annotation is True
    assert leaves[1].first_annotation is False


def test_parse_weighted_selector_rejects_first_in_failover_groups() -> None:
    """Test that [first] annotation is rejected in failover groups (| operator)."""
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "[first]openai:gpt-4|anthropic:claude-3")

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )
    assert "first" in exc_info.value.envelope.message.lower()


def test_parse_weighted_selector_rejects_multiple_first_annotations() -> None:
    """Test that multiple [first] annotations in one weighted group are rejected."""
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "[first]openai:gpt-4^[first]anthropic:claude-3")

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )
    assert "first" in exc_info.value.envelope.message.lower()


def test_parse_weighted_selector_accepts_mixed_weight_and_first_annotations() -> None:
    """Test that [weight=N] and [first] can appear together in any order."""
    parser = CompositeSelectorParser()
    selector = "[weight=3][first]openai:gpt-4^anthropic:claude-3"

    plan = _parse(parser, selector)

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert len(leaves) == 2
    assert leaves[0].weight_annotation == 3
    assert leaves[0].first_annotation is True
    assert leaves[1].first_annotation is False


def test_parse_weighted_selector_first_before_weight() -> None:
    """Test that [first][weight=N] order is also accepted."""
    parser = CompositeSelectorParser()
    selector = "[first][weight=5]openai:gpt-4^anthropic:claude-3"

    plan = _parse(parser, selector)

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert leaves[0].weight_annotation == 5
    assert leaves[0].first_annotation is True


@pytest.mark.parametrize(
    "rejected_form",
    ["[first=false]", "[first=0]", "[first=no]"],
)
def test_parse_weighted_selector_rejects_negative_first_forms(
    rejected_form: str,
) -> None:
    """Test that [first=false], [first=0], [first=no] are rejected."""
    parser = CompositeSelectorParser()
    selector = f"{rejected_form}openai:gpt-4^anthropic:claude-3"

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, selector)

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_weighted_selector_normalizes_first_in_output() -> None:
    """Test that normalized selector includes [first] when present."""
    parser = CompositeSelectorParser()
    selector = "[first][weight=3]openai:gpt-4^anthropic:claude-3"

    plan = _parse(parser, selector)

    assert "[first]" in plan.normalized_selector
    assert "[weight=3]" in plan.normalized_selector


def test_parse_weighted_selector_supports_max_context_prefix() -> None:
    parser = CompositeSelectorParser()

    plan = _parse(
        parser,
        "[weight=2,max_context=128000]openai:gpt-4^anthropic:claude-3",
    )

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert len(leaves) == 2
    assert leaves[0].weight_annotation == 2
    assert leaves[0].max_context_tokens == 128000
    assert leaves[1].max_context_tokens is None


def test_parse_weighted_selector_supports_mixed_prefix_order_in_single_block() -> None:
    parser = CompositeSelectorParser()

    plan = _parse(
        parser,
        "[first,max_context=164000,weight=4]openai:gpt-4^anthropic:claude-3",
    )

    assert plan.root_node.kind == "weighted_group"
    leaves = [child.leaf_selector for child in plan.root_node.children]
    assert len(leaves) == 2
    assert leaves[0].first_annotation is True
    assert leaves[0].weight_annotation == 4
    assert leaves[0].max_context_tokens == 164000
    assert (
        plan.normalized_selector
        == "[weight=4][first][max_context=164000]openai:gpt-4^[weight=1]anthropic:claude-3"
    )


@pytest.mark.parametrize(
    "selector",
    [
        "[max_context=0]openai:gpt-4^anthropic:claude-3",
        "[max_context=-1]openai:gpt-4^anthropic:claude-3",
        "[max_context=abc]openai:gpt-4^anthropic:claude-3",
    ],
)
def test_parse_rejects_invalid_max_context_values(selector: str) -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, selector)

    assert (
        exc_info.value.envelope.code == CompositeValidationErrorCode.INVALID_MAX_CONTEXT
    )


def test_parse_rejects_unknown_prefix_annotation() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(parser, "[foo=1]openai:gpt-4^anthropic:claude-3")

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )


def test_parse_rejects_duplicate_max_context_annotation() -> None:
    parser = CompositeSelectorParser()

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        _parse(
            parser,
            "[max_context=1000,max_context=2000]openai:gpt-4^anthropic:claude-3",
        )

    assert (
        exc_info.value.envelope.code
        == CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT
    )
