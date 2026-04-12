"""Parser and validator for deterministic composite selector plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn

from src.core.domain.composite_routing import (
    CompositeFailoverGroupNode,
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeRoutePlan,
    CompositeRoutingInput,
    CompositeSelectorValidationError,
    CompositeValidationErrorCode,
    CompositeValidationErrorEnvelope,
    CompositeWeightedGroupNode,
)
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_with_params,
)

__all__ = ["CompositeSelectorParser"]

_WEIGHT_PREFIX_PATTERN = re.compile(r"^\[weight=([^\]]+)\](.*)$")
_FIRST_PREFIX_PATTERN = re.compile(r"^\[first(?:=(true|yes|1))?\](.*)$", re.IGNORECASE)
_FIRST_NEGATIVE_PREFIX_PATTERN = re.compile(
    r"^\[first=(false|no|0)\](.*)$", re.IGNORECASE
)
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class _LeafParseResult:
    leaf: CompositeLeafSelector
    normalized_leaf_for_plan: str


class CompositeSelectorParser:
    """Parse flat failover (`|`) and weighted (`^`) composite selectors."""

    def parse(self, routing_input: CompositeRoutingInput) -> CompositeRoutePlan:
        selector = routing_input.selector.strip()
        if not selector:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.SYNTAX_ERROR,
                selector=routing_input.selector,
                message="Composite selector cannot be empty.",
            )

        operator = self._detect_primary_operator(selector)
        if operator is None:
            parsed_single = self._parse_leaf(
                leaf_text=selector,
                is_weighted_group=False,
                routing_input=routing_input,
            )
            return CompositeRoutePlan(
                source_selector=routing_input.selector,
                normalized_selector=parsed_single.normalized_leaf_for_plan,
                root_node=CompositeLeafNode(leaf_selector=parsed_single.leaf),
            )

        parts = self._split_top_level(selector, operator)
        other_operator = "^" if operator == "|" else "|"
        has_mixed_operator = any(
            self._contains_operator_outside_brackets(segment, other_operator)
            for segment in parts
        )
        if has_mixed_operator:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=selector,
                message=(
                    "Composite selector cannot mix failover ('|') and weighted ('^') operators in one string."
                ),
            )

        if operator == "|":
            leaves = [
                self._parse_leaf(
                    leaf_text=segment,
                    is_weighted_group=False,
                    routing_input=routing_input,
                )
                for segment in parts
            ]
            normalized = "|".join(leaf.normalized_leaf_for_plan for leaf in leaves)
            return CompositeRoutePlan(
                source_selector=routing_input.selector,
                normalized_selector=normalized,
                root_node=CompositeFailoverGroupNode(
                    children=[
                        CompositeLeafNode(leaf_selector=item.leaf) for item in leaves
                    ]
                ),
            )

        if operator == "^":
            leaves = [
                self._parse_leaf(
                    leaf_text=segment,
                    is_weighted_group=True,
                    routing_input=routing_input,
                )
                for segment in parts
            ]
            first_count = sum(1 for leaf in leaves if leaf.leaf.first_annotation)
            if first_count > 1:
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                    selector=routing_input.selector,
                    message="Only one branch can have a [first] annotation in a weighted group.",
                )
            normalized = "^".join(leaf.normalized_leaf_for_plan for leaf in leaves)
            return CompositeRoutePlan(
                source_selector=routing_input.selector,
                normalized_selector=normalized,
                root_node=CompositeWeightedGroupNode(
                    children=[
                        CompositeLeafNode(leaf_selector=item.leaf) for item in leaves
                    ]
                ),
            )

        self._raise_validation_error(
            code=CompositeValidationErrorCode.SYNTAX_ERROR,
            selector=selector,
            message="Composite selector contains an unsupported operator token.",
        )

    @staticmethod
    def _detect_primary_operator(selector: str) -> str | None:
        bracket_depth = 0
        for char in selector:
            if char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth > 0:
                bracket_depth -= 1
            elif bracket_depth == 0 and char in {"|", "^"}:
                return char
        return None

    @staticmethod
    def _contains_operator_outside_brackets(selector: str, operator: str) -> bool:
        bracket_depth = 0
        for char in selector:
            if char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth > 0:
                bracket_depth -= 1
            elif bracket_depth == 0 and char == operator:
                return True
        return False

    @staticmethod
    def _split_top_level(selector: str, operator: str) -> list[str]:
        segments: list[str] = []
        current: list[str] = []
        bracket_depth = 0

        for char in selector:
            if char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth > 0:
                bracket_depth -= 1

            if char == operator and bracket_depth == 0:
                segments.append("".join(current))
                current = []
                continue

            current.append(char)

        segments.append("".join(current))
        return segments

    def _parse_leaf(
        self,
        *,
        leaf_text: str,
        is_weighted_group: bool,
        routing_input: CompositeRoutingInput,
    ) -> _LeafParseResult:
        raw_leaf_text = leaf_text.strip()
        if not raw_leaf_text:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.SYNTAX_ERROR,
                selector=routing_input.selector,
                message="Composite selector contains an empty branch.",
            )

        weight_annotation: int | None = None
        first_annotation: bool = False
        normalized_leaf_selector = raw_leaf_text
        normalized_leaf_for_plan = raw_leaf_text

        if is_weighted_group:
            remaining = raw_leaf_text
            weight_annotation = None
            first_annotation = False

            # Extract first prefix regardless of order (could be [first] or [weight=N])
            first_annotation, remaining = self._extract_first_prefix(
                remaining,
                source_selector=routing_input.selector,
            )
            weight_annotation, remaining = self._extract_weight_prefix(
                remaining,
                source_selector=routing_input.selector,
            )

            # If first pass didn't find [first], try after extracting [weight]
            if not first_annotation:
                first_annotation, remaining = self._extract_first_prefix(
                    remaining,
                    source_selector=routing_input.selector,
                )

            normalized_leaf_selector = remaining
            if weight_annotation is None:
                weight_annotation = 1
            prefix_parts = ""
            prefix_parts += f"[weight={weight_annotation}]"
            prefix_parts += "[first]" if first_annotation else ""
            normalized_leaf_for_plan = f"{prefix_parts}{normalized_leaf_selector}"
        elif raw_leaf_text.startswith("[weight="):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=routing_input.selector,
                message="Weight annotations are only supported for weighted ('^') selectors.",
            )
        elif "[first" in raw_leaf_text.lower() and raw_leaf_text.startswith("[first"):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=routing_input.selector,
                message="First annotations are only supported for weighted ('^') selectors.",
            )

        parsed_leaf = parse_model_with_params(
            normalized_leaf_selector,
            default_backend=routing_input.default_backend,
        )

        if (
            routing_input.require_explicit_backend
            and not has_explicit_backend_selector(normalized_leaf_selector)
        ):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.INVALID_LEAF,
                selector=normalized_leaf_selector,
                message=(
                    "Selector must use explicit backend:model syntax for this routing surface."
                ),
            )

        if has_explicit_backend_selector(normalized_leaf_selector):
            if (
                not parsed_leaf.backend_type.strip()
                or not parsed_leaf.model_name.strip()
            ):
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.INVALID_LEAF,
                    selector=normalized_leaf_selector,
                    message=(
                        "Explicit backend selector must contain both backend and model segments."
                    ),
                )
        elif not parsed_leaf.model_name.strip():
            self._raise_validation_error(
                code=CompositeValidationErrorCode.INVALID_LEAF,
                selector=normalized_leaf_selector,
                message="Leaf selector model segment cannot be empty.",
            )

        leaf = CompositeLeafSelector(
            raw_selector=raw_leaf_text,
            normalized_selector=normalized_leaf_selector,
            weight_annotation=weight_annotation if is_weighted_group else None,
            first_annotation=first_annotation if is_weighted_group else False,
            uri_params=parsed_leaf.uri_params,
            backend_type=parsed_leaf.backend_type,
            model_name=parsed_leaf.model_name,
        )
        return _LeafParseResult(
            leaf=leaf,
            normalized_leaf_for_plan=normalized_leaf_for_plan,
        )

    def _extract_weight_prefix(
        self,
        leaf_text: str,
        *,
        source_selector: str,
    ) -> tuple[int | None, str]:
        if "[weight=" in leaf_text and not leaf_text.startswith("[weight="):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message="[weight=N] annotations must appear as a prefix.",
            )

        match = _WEIGHT_PREFIX_PATTERN.match(leaf_text)
        if not match:
            return None, leaf_text

        weight_raw = (match.group(1) or "").strip()
        trailing_selector = match.group(2) or ""
        if not trailing_selector or trailing_selector[0].isspace():
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message=(
                    "[weight=N] must appear immediately before a selector without whitespace."
                ),
            )

        if not _INTEGER_PATTERN.fullmatch(weight_raw):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.INVALID_WEIGHT,
                selector=source_selector,
                message=f"Invalid [weight=N] annotation '{weight_raw}'.",
            )

        weight_value = int(weight_raw)
        if weight_value <= 0:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.INVALID_WEIGHT,
                selector=source_selector,
                message=f"Weight must be a positive integer, received {weight_value}.",
            )

        return weight_value, trailing_selector.strip()

    def _extract_first_prefix(
        self,
        leaf_text: str,
        *,
        source_selector: str,
    ) -> tuple[bool, str]:
        # Reject negative forms like [first=false], [first=0], [first=no]
        neg_match = _FIRST_NEGATIVE_PREFIX_PATTERN.match(leaf_text)
        if neg_match:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message=f"Unsupported [first] annotation '{neg_match.group(0)}'. Use [first] without negation.",
            )

        match = _FIRST_PREFIX_PATTERN.match(leaf_text)
        if not match:
            return False, leaf_text

        trailing_selector = match.group(2) or ""
        if not trailing_selector or trailing_selector[0].isspace():
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message=(
                    "[first] must appear immediately before a selector without whitespace."
                ),
            )

        return True, trailing_selector.strip()

    @staticmethod
    def _raise_validation_error(
        *,
        code: CompositeValidationErrorCode,
        selector: str,
        message: str,
    ) -> NoReturn:
        envelope = CompositeValidationErrorEnvelope(
            code=code,
            message=message,
            selector_echo=selector,
        )
        raise CompositeSelectorValidationError(envelope)
