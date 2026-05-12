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

_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_ANNOTATION_TRUE_VALUES = {"true", "yes", "1"}
_ANNOTATION_FALSE_VALUES = {"false", "no", "0"}


@dataclass(frozen=True)
class _LeafParseResult:
    leaf: CompositeLeafSelector
    normalized_leaf_for_plan: str


@dataclass(frozen=True)
class _PrefixAnnotations:
    weight_annotation: int | None = None
    first_annotation: bool = False
    thinker_annotation: bool = False
    max_context_tokens: int | None = None


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
            thinker_count = sum(1 for leaf in leaves if leaf.leaf.thinker_annotation)
            if thinker_count > 1:
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                    selector=routing_input.selector,
                    message="Only one branch can have a [thinker] annotation in a weighted group.",
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

        annotations, normalized_leaf_selector = self._extract_prefix_annotations(
            raw_leaf_text,
            source_selector=routing_input.selector,
        )
        weight_annotation = annotations.weight_annotation
        first_annotation = annotations.first_annotation

        if weight_annotation is not None and not is_weighted_group:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=routing_input.selector,
                message="Weight annotations are only supported for weighted ('^') selectors.",
            )
        if first_annotation and not is_weighted_group:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=routing_input.selector,
                message="First annotations are only supported for weighted ('^') selectors.",
            )
        if annotations.thinker_annotation and not is_weighted_group:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=routing_input.selector,
                message="Thinker annotations are only supported for weighted ('^') selectors.",
            )

        if is_weighted_group:
            if weight_annotation is None:
                weight_annotation = 1
            prefix_parts = f"[weight={weight_annotation}]"
            if first_annotation:
                prefix_parts += "[first]"
            if annotations.thinker_annotation:
                prefix_parts += "[thinker]"
            if annotations.max_context_tokens is not None:
                prefix_parts += f"[max_context={annotations.max_context_tokens}]"
            normalized_leaf_for_plan = f"{prefix_parts}{normalized_leaf_selector}"
        elif annotations.max_context_tokens is not None:
            normalized_leaf_for_plan = (
                f"[max_context={annotations.max_context_tokens}]"
                f"{normalized_leaf_selector}"
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
            thinker_annotation=(
                annotations.thinker_annotation if is_weighted_group else False
            ),
            max_context_tokens=annotations.max_context_tokens,
            uri_params=parsed_leaf.uri_params,
            backend_type=parsed_leaf.backend_type,
            model_name=parsed_leaf.model_name,
        )
        return _LeafParseResult(
            leaf=leaf,
            normalized_leaf_for_plan=normalized_leaf_for_plan,
        )

    def _extract_prefix_annotations(
        self,
        leaf_text: str,
        *,
        source_selector: str,
    ) -> tuple[_PrefixAnnotations, str]:
        remaining = leaf_text
        weight_annotation: int | None = None
        first_annotation = False
        thinker_annotation = False
        max_context_tokens: int | None = None

        while remaining.startswith("["):
            closing_index = remaining.find("]")
            if closing_index <= 0:
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.SYNTAX_ERROR,
                    selector=source_selector,
                    message="Unclosed annotation prefix bracket in selector branch.",
                )

            annotation_block = remaining[1:closing_index].strip()
            trailing = remaining[closing_index + 1 :]
            if not annotation_block:
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                    selector=source_selector,
                    message="Empty annotation block is not supported.",
                )

            entries = [item.strip() for item in annotation_block.split(",")]
            if any(not item for item in entries):
                self._raise_validation_error(
                    code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                    selector=source_selector,
                    message="Malformed annotation list in selector branch.",
                )

            for entry in entries:
                key: str
                raw_value: str | None
                if "=" in entry:
                    left, right = entry.split("=", 1)
                    key = left.strip().lower()
                    raw_value = right.strip()
                else:
                    key = entry.strip().lower()
                    raw_value = None

                if key == "weight":
                    if weight_annotation is not None:
                        self._raise_validation_error(
                            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                            selector=source_selector,
                            message="Duplicate [weight=N] annotations are not supported.",
                        )
                    weight_annotation = self._parse_positive_integer_annotation(
                        key="weight",
                        raw_value=raw_value,
                        source_selector=source_selector,
                        error_code=CompositeValidationErrorCode.INVALID_WEIGHT,
                    )
                    continue

                if key == "max_context":
                    if max_context_tokens is not None:
                        self._raise_validation_error(
                            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                            selector=source_selector,
                            message="Duplicate [max_context=N] annotations are not supported.",
                        )
                    max_context_tokens = self._parse_positive_integer_annotation(
                        key="max_context",
                        raw_value=raw_value,
                        source_selector=source_selector,
                        error_code=CompositeValidationErrorCode.INVALID_MAX_CONTEXT,
                    )
                    continue

                if key == "first":
                    if first_annotation:
                        self._raise_validation_error(
                            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                            selector=source_selector,
                            message="Duplicate [first] annotations are not supported.",
                        )
                    first_annotation = self._parse_first_annotation(
                        raw_value=raw_value,
                        source_selector=source_selector,
                    )
                    continue

                if key == "thinker":
                    if thinker_annotation:
                        self._raise_validation_error(
                            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                            selector=source_selector,
                            message="Duplicate [thinker] annotations are not supported.",
                        )
                    thinker_annotation = self._parse_thinker_annotation(
                        raw_value=raw_value,
                        source_selector=source_selector,
                    )
                    continue

                self._raise_validation_error(
                    code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                    selector=source_selector,
                    message=f"Unsupported annotation key '{key}'.",
                )

            remaining = trailing

        if leaf_text.startswith("[") and (not remaining or remaining[0].isspace()):
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message="Annotation prefixes must appear immediately before a selector without whitespace.",
            )

        return (
            _PrefixAnnotations(
                weight_annotation=weight_annotation,
                first_annotation=first_annotation,
                thinker_annotation=thinker_annotation,
                max_context_tokens=max_context_tokens,
            ),
            remaining.strip(),
        )

    def _parse_positive_integer_annotation(
        self,
        *,
        key: str,
        raw_value: str | None,
        source_selector: str,
        error_code: CompositeValidationErrorCode,
    ) -> int:
        value_text = "" if raw_value is None else raw_value.strip()
        if not value_text:
            self._raise_validation_error(
                code=error_code,
                selector=source_selector,
                message=f"Invalid [{key}=N] annotation '{value_text}'.",
            )

        if not _INTEGER_PATTERN.fullmatch(value_text):
            self._raise_validation_error(
                code=error_code,
                selector=source_selector,
                message=f"Invalid [{key}=N] annotation '{value_text}'.",
            )

        value = int(value_text)
        if value <= 0:
            self._raise_validation_error(
                code=error_code,
                selector=source_selector,
                message=f"{key} must be a positive integer, received {value}.",
            )
        return value

    def _parse_first_annotation(
        self,
        *,
        raw_value: str | None,
        source_selector: str,
    ) -> bool:
        if raw_value is None:
            return True

        normalized_value = raw_value.strip().lower()
        if normalized_value in _ANNOTATION_TRUE_VALUES:
            return True
        if normalized_value in _ANNOTATION_FALSE_VALUES:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message=f"Unsupported [first] annotation '[first={raw_value}]'. Use [first] without negation.",
            )
        self._raise_validation_error(
            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
            selector=source_selector,
            message=(
                f"Unsupported [first] annotation '[first={raw_value}]'. "
                "Accepted forms: [first], [first=1], [first=yes], [first=true]."
            ),
        )

    def _parse_thinker_annotation(
        self,
        *,
        raw_value: str | None,
        source_selector: str,
    ) -> bool:
        if raw_value is None:
            return True

        normalized_value = raw_value.strip().lower()
        if normalized_value in _ANNOTATION_TRUE_VALUES:
            return True
        if normalized_value in _ANNOTATION_FALSE_VALUES:
            self._raise_validation_error(
                code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
                selector=source_selector,
                message=(
                    f"Unsupported [thinker] annotation '[thinker={raw_value}]'. "
                    "Use [thinker] without negation."
                ),
            )
        self._raise_validation_error(
            code=CompositeValidationErrorCode.UNSUPPORTED_CONSTRUCT,
            selector=source_selector,
            message=(
                f"Unsupported [thinker] annotation '[thinker={raw_value}]'. "
                "Accepted forms: [thinker], [thinker=1], [thinker=yes], [thinker=true]."
            ),
        )

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
