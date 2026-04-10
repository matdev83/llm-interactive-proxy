from __future__ import annotations

import pytest
from src.core.domain.composite_routing import (
    CompositeLeafNode,
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
        if isinstance(child, CompositeLeafNode)
    ]
    assert normalized_children == ["openai:gpt-4", "anthropic:claude-3-5-sonnet"]


def test_parse_weighted_selector_applies_default_and_explicit_weights() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(parser, "[weight=3]openai:gpt-4^anthropic:claude-3-haiku")

    assert plan.root_node.kind == "weighted_group"
    weights = [
        child.leaf_selector.weight_annotation
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
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


def test_parse_weighted_selector_allows_pipe_in_query_values() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(
        parser,
        "[weight=3]openai:gpt-4^" "[weight=1]anthropic:claude-3-5-sonnet?note=foo|bar",
    )

    assert plan.root_node.kind == "weighted_group"
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
    assert [leaf.weight_annotation for leaf in leaves] == [3, 1]
    assert leaves[1].uri_params == {"note": "foo|bar"}


def test_parse_failover_selector_allows_caret_in_query_values() -> None:
    parser = CompositeSelectorParser()
    plan = _parse(
        parser,
        "openai:gpt-4|anthropic:claude-3-5-sonnet?note=foo^bar",
    )

    assert plan.root_node.kind == "failover_group"
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
    assert leaves[1].uri_params == {"note": "foo^bar"}


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
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
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
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
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
    """Grammar limitation: ``^`` and ``|`` are always composite operators.

    The flat grammar cannot distinguish an operator inside a query-parameter
    value from a composite separator.  URL-encode same-operator characters
    (``%5E`` for ``^``, ``%7C`` for ``|``) in query values to avoid false
    splits.  Alternate operators in query values are inherently safe because
    they are not the primary split operator.
    """
    parser = CompositeSelectorParser()

    plan = _parse(parser, "openai:gpt-4?filter=a^b")
    assert plan.root_node.kind == "weighted_group"
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
    assert leaves[0].uri_params == {"filter": "a"}
    assert leaves[1].model_name == "b"

    plan_pipe = _parse(parser, "openai:gpt-4?filter=a|b")
    assert plan_pipe.root_node.kind == "failover_group"


def test_parse_url_encoded_operator_in_query_value_preserves_value() -> None:
    """URL-encoded operators are treated as literal query content, not splits."""
    parser = CompositeSelectorParser()
    plan = _parse(parser, "openai:gpt-4^anthropic:claude-3?note=x%5Ey")

    assert plan.root_node.kind == "weighted_group"
    leaves = [
        child.leaf_selector
        for child in plan.root_node.children
        if isinstance(child, CompositeLeafNode)
    ]
    assert len(leaves) == 2
    assert leaves[1].uri_params == {"note": "x^y"}
