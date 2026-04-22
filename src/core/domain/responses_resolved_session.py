"""Session resolution snapshot for Responses API multi-turn linkage."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.domain.responses_domain import ResponsesOutputItem


@dataclass(frozen=True)
class ResponsesResolvedSession:
    output_items: list[ResponsesOutputItem]
    instructions: str | None


def effective_instructions_for_chained_turn(
    request_instructions: str | None,
    prior_instructions: str | None,
) -> str | None:
    if request_instructions is not None:
        return request_instructions
    return prior_instructions
