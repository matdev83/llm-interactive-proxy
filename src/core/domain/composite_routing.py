"""Typed domain contracts for composite selector routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator
from pydantic.types import JsonValue

from src.core.common.exceptions import ValidationError
from src.core.domain.configuration.failure_handling_config import (
    DEFAULT_FAILURE_HANDLING_CONFIG,
)
from src.core.interfaces.model_bases import DomainModel

COMPOSITE_ROUTING_GRAMMAR_VERSION = "composite-routing-v1"
_DEFAULT_BRANCH_HISTORY_LIMIT = 32
_MAX_OPERATOR_MESSAGE_CHARS = 256
_MAX_SELECTOR_ECHO_CHARS = 512
_TRUNCATION_MARKER = "...(truncated)"


def _truncate_for_operator_visibility(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker_budget = max(0, limit - len(_TRUNCATION_MARKER))
    return f"{value[:marker_budget]}{_TRUNCATION_MARKER}"


class RoutingSurface(str, Enum):
    """Selector-routing surface that initiated composite evaluation."""

    MAIN = "main"
    AUXILIARY = "auxiliary"
    QUALITY_VERIFIER = "quality_verifier"
    REPLACEMENT_BRIDGE = "replacement_bridge"


class CompositeValidationErrorCode(str, Enum):
    """Stable taxonomy for pre-execution composite selector validation errors."""

    SYNTAX_ERROR = "syntax_error"
    UNSUPPORTED_CONSTRUCT = "unsupported_construct"
    INVALID_WEIGHT = "invalid_weight"
    INVALID_MAX_CONTEXT = "invalid_max_context"
    INVALID_HANDICAP = "invalid_handicap"
    INVALID_TTFT_TIMEOUT = "invalid_ttft_timeout"
    INVALID_LEAF = "invalid_leaf"


class CompositeRoutingErrorCode(str, Enum):
    """Typed error outcomes for shared routing entry-point consumers."""

    ROUTING_VALIDATION_FAILED = "routing_validation_failed"
    ROUTING_EXHAUSTED = "routing_exhausted"


class CompositeBranchOutcomeCategory(str, Enum):
    """Bounded branch-outcome categories for diagnostics history."""

    VALIDATION_REJECTED = "validation_rejected"
    INELIGIBLE = "ineligible"
    RUNTIME_FAILED = "runtime_failed"
    NOT_SELECTED = "not_selected"
    SELECTED = "selected"
    EXHAUSTED = "exhausted"


class CompositeValidationErrorEnvelope(DomainModel):
    """Operator-safe validation error payload for composite parsing/validation."""

    model_config = ConfigDict(frozen=True)

    code: CompositeValidationErrorCode
    message: str
    selector_echo: str
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _bound_message(cls, value: str) -> str:
        compact = " ".join(value.split())
        return _truncate_for_operator_visibility(compact, _MAX_OPERATOR_MESSAGE_CHARS)

    @field_validator("selector_echo")
    @classmethod
    def _bound_selector_echo(cls, value: str) -> str:
        compact = " ".join(value.split())
        return _truncate_for_operator_visibility(compact, _MAX_SELECTOR_ECHO_CHARS)


class CompositeSelectorValidationError(ValidationError):
    """Typed exception carrying the stable composite validation envelope."""

    def __init__(self, envelope: CompositeValidationErrorEnvelope):
        super().__init__(
            message=envelope.message,
            details={"composite_validation": envelope.model_dump(mode="json")},
        )
        self.envelope = envelope


class CompositeLeafSelector(DomainModel):
    """Parsed representation of one composite leaf selector."""

    model_config = ConfigDict(frozen=True)

    raw_selector: str
    normalized_selector: str
    weight_annotation: int | None = None
    first_annotation: bool = False
    thinker_annotation: bool = False
    max_context_tokens: int | None = None
    handicap_seconds: float = 0.0
    ttft_timeout_seconds: float = 0.0
    uri_params: dict[str, JsonValue] = Field(default_factory=dict)
    backend_type: str = ""
    model_name: str = ""
    embedded_selector: str | None = None

    @field_validator("raw_selector", "normalized_selector")
    @classmethod
    def _require_selector_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector text cannot be empty")
        return stripped

    @field_validator("weight_annotation")
    @classmethod
    def _validate_weight_annotation(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("weight annotation must be positive")
        return value

    @field_validator("max_context_tokens")
    @classmethod
    def _validate_max_context_tokens(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("max_context_tokens must be positive")
        return value

    @field_validator("first_annotation")
    @classmethod
    def _validate_first_annotation(cls, value: bool) -> bool:
        return value

    @field_validator("thinker_annotation")
    @classmethod
    def _validate_thinker_annotation(cls, value: bool) -> bool:
        return value

    @field_validator("handicap_seconds", "ttft_timeout_seconds")
    @classmethod
    def _validate_non_negative_parallel_timing(cls, value: float) -> float:
        if value < 0:
            raise ValueError("parallel timing values must be non-negative")
        return float(value)


class CompositeLeafNode(DomainModel):
    """Leaf node that can be resolved by existing single-target selector semantics."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["leaf"] = "leaf"
    leaf_selector: CompositeLeafSelector


class CompositeFailoverGroupNode(DomainModel):
    """Ordered failover group (`|`) represented as a flat ordered branch list."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["failover_group"] = "failover_group"
    children: list[CompositeLeafNode]

    @field_validator("children")
    @classmethod
    def _require_multiple_children(
        cls, value: list[CompositeLeafNode]
    ) -> list[CompositeLeafNode]:
        if len(value) < 2:
            raise ValueError("failover groups require at least two branches")
        return value


class CompositeWeightedGroupNode(DomainModel):
    """Weighted selection group (`^`) represented as a flat branch list."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["weighted_group"] = "weighted_group"
    children: list[CompositeLeafNode]

    @field_validator("children")
    @classmethod
    def _require_multiple_children(
        cls, value: list[CompositeLeafNode]
    ) -> list[CompositeLeafNode]:
        if len(value) < 2:
            raise ValueError("weighted groups require at least two branches")
        return value


class CompositeParallelGroupNode(DomainModel):
    """Parallel racing group (`!`) represented as a flat branch list."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["parallel_group"] = "parallel_group"
    children: list[CompositeLeafNode]

    @field_validator("children")
    @classmethod
    def _require_multiple_children(
        cls, value: list[CompositeLeafNode]
    ) -> list[CompositeLeafNode]:
        if len(value) < 2:
            raise ValueError("parallel groups require at least two branches")
        return value


CompositeNode = (
    CompositeLeafNode
    | CompositeFailoverGroupNode
    | CompositeWeightedGroupNode
    | CompositeParallelGroupNode
)
CompositeNodeDiscriminated = Annotated[CompositeNode, Field(discriminator="kind")]


class CompositeRoutePlan(DomainModel):
    """Immutable parsed plan for one raw selector string."""

    model_config = ConfigDict(frozen=True)

    source_selector: str
    normalized_selector: str
    root_node: CompositeNodeDiscriminated
    grammar_version: str = COMPOSITE_ROUTING_GRAMMAR_VERSION

    @field_validator("source_selector", "normalized_selector")
    @classmethod
    def _require_non_empty_selector(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector cannot be empty")
        return stripped


class CompositeBranchRecord(DomainModel):
    """One branch transition record used for bounded diagnostics history."""

    model_config = ConfigDict(frozen=True)

    selector_fragment: str
    outcome_category: CompositeBranchOutcomeCategory
    backend: str | None = None
    model: str | None = None
    reason_code: str | None = None

    @field_validator("selector_fragment")
    @classmethod
    def _bound_selector_fragment(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector_fragment cannot be empty")
        return _truncate_for_operator_visibility(stripped, _MAX_SELECTOR_ECHO_CHARS)


@dataclass(slots=True)
class CompositeRoutingAttemptContext:
    """Request-scoped shared hop budget and bounded branch history."""

    surface: RoutingSurface
    max_hops: int
    history_limit: int = _DEFAULT_BRANCH_HISTORY_LIMIT
    hop_count: int = 0
    content_started: bool = False
    exhaustion_reason: str | None = None
    branch_history: list[CompositeBranchRecord] = field(default_factory=list)
    branch_history_omitted: int = 0

    @staticmethod
    def resolve_max_hops(configured_max_hops: int | None) -> int:
        if isinstance(configured_max_hops, int) and configured_max_hops > 0:
            return configured_max_hops
        return DEFAULT_FAILURE_HANDLING_CONFIG.max_failover_hops

    @classmethod
    def create(
        cls,
        *,
        surface: RoutingSurface,
        configured_max_hops: int | None = None,
        history_limit: int = _DEFAULT_BRANCH_HISTORY_LIMIT,
    ) -> CompositeRoutingAttemptContext:
        bounded_history_limit = max(1, history_limit)
        return cls(
            surface=surface,
            max_hops=cls.resolve_max_hops(configured_max_hops),
            history_limit=bounded_history_limit,
        )

    @property
    def is_exhausted(self) -> bool:
        return self.hop_count >= self.max_hops

    @property
    def remaining_hops(self) -> int:
        remaining = self.max_hops - self.hop_count
        return remaining if remaining > 0 else 0

    def consume_hop(self, *, reason_code: str) -> bool:
        if self.is_exhausted:
            if self.exhaustion_reason is None:
                self.exhaustion_reason = reason_code
            return False

        self.hop_count += 1
        if self.is_exhausted and self.exhaustion_reason is None:
            self.exhaustion_reason = reason_code
        return True

    def mark_content_started(self) -> None:
        self.content_started = True

    def record_branch(self, record: CompositeBranchRecord) -> None:
        self.branch_history.append(record)
        if len(self.branch_history) > self.history_limit:
            overflow = len(self.branch_history) - self.history_limit
            if overflow > 0:
                del self.branch_history[:overflow]
                self.branch_history_omitted += overflow


class CompositeRoutingInput(DomainModel):
    """Surface-aware input envelope consumed by the shared routing entry point."""

    model_config = ConfigDict(frozen=True)

    selector: str
    surface: RoutingSurface
    require_explicit_backend: bool = False
    configured_max_hops: int | None = None
    max_branch_history: int = _DEFAULT_BRANCH_HISTORY_LIMIT
    default_backend: str = ""
    prefer_first_weighted_branch: bool = False
    request_context_tokens: int | None = None
    interleaved_thinking_weighted_cycle_state: dict[str, JsonValue] | None = None

    @field_validator("selector")
    @classmethod
    def _require_selector(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selector cannot be empty")
        return stripped

    @field_validator("max_branch_history")
    @classmethod
    def _bound_history_limit(cls, value: int) -> int:
        return max(1, value)

    @field_validator("request_context_tokens")
    @classmethod
    def _bound_request_context_tokens(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(0, value)


class CompositeRoutingSuccess(DomainModel):
    """Outcome envelope for successful branch selection."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    kind: Literal["selected_target"] = "selected_target"
    selected_selector: str
    selected_backend: str | None = None
    selected_model: str | None = None
    attempt_context: CompositeRoutingAttemptContext
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("selected_selector")
    @classmethod
    def _require_selected_selector(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selected_selector cannot be empty")
        return stripped


class CompositeRoutingFailure(DomainModel):
    """Outcome envelope for deterministic composite routing failures."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    kind: Literal["routing_error"] = "routing_error"
    error_code: CompositeRoutingErrorCode
    message: str
    attempt_context: CompositeRoutingAttemptContext
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _bound_failure_message(cls, value: str) -> str:
        compact = " ".join(value.split())
        return _truncate_for_operator_visibility(compact, _MAX_OPERATOR_MESSAGE_CHARS)


CompositeRoutingOutcome = CompositeRoutingSuccess | CompositeRoutingFailure


__all__ = [
    "COMPOSITE_ROUTING_GRAMMAR_VERSION",
    "CompositeBranchOutcomeCategory",
    "CompositeBranchRecord",
    "CompositeFailoverGroupNode",
    "CompositeLeafNode",
    "CompositeLeafSelector",
    "CompositeNode",
    "CompositeNodeDiscriminated",
    "CompositeRoutePlan",
    "CompositeRoutingAttemptContext",
    "CompositeRoutingErrorCode",
    "CompositeRoutingInput",
    "CompositeSelectorValidationError",
    "CompositeValidationErrorCode",
    "CompositeValidationErrorEnvelope",
    "CompositeParallelGroupNode",
    "CompositeWeightedGroupNode",
    "RoutingSurface",
]
