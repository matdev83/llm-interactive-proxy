"""Tests for StructuredOutputMiddleware error handling."""

from __future__ import annotations

import pytest
from src.core.services.structured_output_middleware import StructuredOutputMiddleware


class DummyJsonRepairService:
    """A dummy repair service that raises an unexpected error."""

    def process_structured_response(
        self, **_: object
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("boom")


class DummyResponse:
    """Response object with content and metadata attributes."""

    def __init__(self) -> None:
        self.content = "{}"
        self.metadata: dict[str, object] | None = {}


@pytest.mark.asyncio
async def test_unexpected_error_raises_when_strict_validation_enabled() -> None:
    middleware = StructuredOutputMiddleware(DummyJsonRepairService())
    response = DummyResponse()
    context = {
        "response_schema": {"type": "object"},
        "strict_schema_validation": True,
    }

    with pytest.raises(RuntimeError, match="boom"):
        await middleware.process(
            response=response,
            session_id="session-123",
            context=context,
        )
