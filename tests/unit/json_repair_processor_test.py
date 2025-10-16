from __future__ import annotations

import asyncio
from typing import Any

import pytest
from src.core.common.exceptions import ValidationError
from src.core.domain.streaming_content import StreamingContent
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor


class FailingJsonRepairService(JsonRepairService):
    """Test double that simulates a repair failure without raising."""

    def repair_and_validate_json(
        self,
        json_string: str,
        schema: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        return None


class RaisingValidationService(JsonRepairService):
    """Test double that raises a ValidationError when strict mode is enabled."""

    def repair_and_validate_json(
        self,
        json_string: str,
        schema: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        raise ValidationError(message="invalid", details={})


def test_json_repair_processor_flushes_raw_buffer_when_repair_returns_none() -> None:
    processor = JsonRepairProcessor(
        repair_service=FailingJsonRepairService(),
        buffer_cap_bytes=1024,
        strict_mode=False,
    )

    chunk = StreamingContent(content='{"foo": "bar"}', is_done=False)

    result = asyncio.run(processor.process(chunk))

    assert result.content == '{"foo": "bar"}'


def test_json_repair_processor_appends_null_when_value_missing() -> None:
    processor = JsonRepairProcessor(
        repair_service=FailingJsonRepairService(),
        buffer_cap_bytes=1024,
        strict_mode=False,
    )

    chunk = StreamingContent(content='{"foo":', is_done=True)

    result = asyncio.run(processor.process(chunk))

    assert result.content == '{"foo": null'


def test_json_repair_processor_propagates_validation_error_in_strict_mode() -> None:
    processor = JsonRepairProcessor(
        repair_service=RaisingValidationService(),
        buffer_cap_bytes=1024,
        strict_mode=True,
    )

    chunk = StreamingContent(content='{"foo": "bar"}', is_done=True)

    with pytest.raises(ValidationError):
        asyncio.run(processor.process(chunk))
