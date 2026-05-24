"""Tests for StructuredOutputMiddleware error handling."""

from __future__ import annotations

import pytest
from src.core.common.exceptions import ValidationError
from src.core.services.structured_output_middleware import (
    StructuredOutputFeature,
    StructuredOutputMiddleware,
)


class DummyJsonRepairService:
    """A dummy repair service that raises an unexpected error."""

    def process_structured_response(
        self, **_: object
    ) -> tuple[str, dict[str, object] | None]:
        raise RuntimeError("boom")


class FailingSchemaJsonRepairService:
    """Raises ValidationError like a real schema failure."""

    def process_structured_response(
        self, **_: object
    ) -> tuple[str, dict[str, object] | None]:
        raise ValidationError("schema failed")


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


class ResponseNoMetadata:
    """Like some adapters: content present but metadata not initialized."""

    def __init__(self) -> None:
        self.content = "{}"
        self.metadata: dict[str, object] | None = None


@pytest.mark.asyncio
async def test_structured_output_feature_attaches_error_when_metadata_is_none() -> None:
    feature = StructuredOutputFeature(FailingSchemaJsonRepairService())
    response = ResponseNoMetadata()
    context = {
        "response_schema": {"type": "object"},
        "strict_schema_validation": False,
    }
    out = await feature.process_chunk(
        payload=response,
        session_id="session-456",
        context=context,
        is_streaming=False,
    )
    assert out is response
    assert response.metadata is not None
    assert response.metadata.get("structured_output_validated") is False
    assert "structured_output_error" in response.metadata
    assert response.metadata.get("schema_validation_attempted") is True
