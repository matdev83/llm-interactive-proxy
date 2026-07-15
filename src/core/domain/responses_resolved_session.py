"""Session resolution snapshot for Responses API multi-turn linkage."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.responses_domain import ResponsesInputItem, ResponsesOutputItem

ResponsesHistoryItem = ResponsesInputItem | ResponsesOutputItem


@dataclass(frozen=True)
class ResponsesResolvedSession:
    output_items: list[ResponsesOutputItem]
    instructions: str | None
    # Complete visible transcript for providers whose runtime may be reaped
    # between turns.  The output-only field above remains for compatibility
    # with existing provider projectors and older stored entries.
    history_items: list[ResponsesHistoryItem] = field(default_factory=list)


def effective_instructions_for_chained_turn(
    request_instructions: str | None,
    prior_instructions: str | None,
) -> str | None:
    if request_instructions is not None:
        return request_instructions
    return prior_instructions
