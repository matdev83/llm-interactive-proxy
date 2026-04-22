"""Protocol for Responses API session store (previous_response_id continuity)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.core.domain.responses_domain import ResponsesOutputItem
from src.core.domain.responses_resolved_session import ResponsesResolvedSession


@runtime_checkable
class IResponsesSessionStore(Protocol):
    async def store(
        self,
        response_id: str,
        output_items: list[ResponsesOutputItem],
        ttl_seconds: int | None = None,
        *,
        instructions: str | None = None,
    ) -> None: ...

    async def resolve(
        self,
        previous_response_id: str,
    ) -> ResponsesResolvedSession | None: ...
