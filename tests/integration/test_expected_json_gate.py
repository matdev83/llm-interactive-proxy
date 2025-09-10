from __future__ import annotations

import pytest
from jsonschema.exceptions import ValidationError
from src.core.app.middleware.json_repair_middleware import JsonRepairMiddleware
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


def _middleware_with_schema() -> MiddlewareApplicationProcessor:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    }
    cfg = AppConfig(
        session=SessionConfig(
            json_repair_enabled=True,
            json_repair_strict_mode=False,  # rely on gating conditions
            json_repair_schema=schema,
        )
    )
    mw = JsonRepairMiddleware(cfg, JsonRepairService())
    return MiddlewareApplicationProcessor([mw])


@pytest.mark.asyncio
async def test_expected_json_flag_triggers_strict() -> None:
    processor = _middleware_with_schema()
    # Invalid per schema (a should be integer)
    sc = StreamingContent(
        content='{"a": "x"}',
        metadata={"session_id": "s1", "non_streaming": True, "expected_json": True},
    )
    with pytest.raises(ValidationError):
        await processor.process(sc)


@pytest.mark.asyncio
async def test_content_type_json_triggers_strict() -> None:
    processor = _middleware_with_schema()
    # Reparable trailing comma should pass strict mode
    sc = StreamingContent(
        content="{'a': 2,}",
        metadata={
            "session_id": "s1",
            "non_streaming": True,
            "headers": {"Content-Type": "application/json"},
        },
    )
    out = await processor.process(sc)
    assert out.content == '{"a": 2}'
