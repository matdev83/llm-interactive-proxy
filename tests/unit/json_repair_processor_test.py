from __future__ import annotations

import asyncio
from typing import Any

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


def test_json_repair_processor_flushes_raw_buffer_when_repair_returns_none() -> None:
    processor = JsonRepairProcessor(
        repair_service=FailingJsonRepairService(),
        buffer_cap_bytes=1024,
        strict_mode=False,
    )

    chunk = StreamingContent(content='{"foo": "bar"}', is_done=False)

    result = asyncio.run(processor.process(chunk))

    assert result.content == '{"foo": "bar"}'
