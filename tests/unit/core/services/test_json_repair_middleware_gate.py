from __future__ import annotations

import pytest
from jsonschema.exceptions import ValidationError
from src.core.app.middleware.json_repair_middleware import JsonRepairMiddleware
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.json_repair_service import JsonRepairService


@pytest.fixture()
def json_repair_service() -> JsonRepairService:
    return JsonRepairService()


@pytest.fixture()
def config() -> AppConfig:
    # Include a schema to trigger strict mode gating
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    }
    return AppConfig(
        session=SessionConfig(
            json_repair_enabled=True,
            json_repair_strict_mode=False,
            json_repair_schema=schema,
        )
    )


@pytest.fixture()
def middleware(
    config: AppConfig, json_repair_service: JsonRepairService
) -> JsonRepairMiddleware:
    return JsonRepairMiddleware(config, json_repair_service)


@pytest.mark.asyncio
async def test_gate_non_stream_non_json_best_effort(
    middleware: JsonRepairMiddleware,
) -> None:
    # No content-type, no expected_json flag -> non-strict best-effort
    response = ProcessedResponse(content="{'a': 1,}")
    out = await middleware.process(response, "sid", {})
    assert out.metadata.get("repaired") is True
    assert out.content == '{"a": 1}'


@pytest.mark.asyncio
async def test_gate_expected_json_strict_raises(
    middleware: JsonRepairMiddleware,
) -> None:
    # expected_json=True forces strict; invalid per schema should raise
    response = ProcessedResponse(content='{"a": "x"}')
    with pytest.raises(ValidationError):
        await middleware.process(response, "sid", {"expected_json": True})


@pytest.mark.asyncio
async def test_gate_content_type_json_strict_applies(
    middleware: JsonRepairMiddleware,
) -> None:
    # Content-Type JSON triggers strict; but repair succeeds for trailing comma
    response = ProcessedResponse(
        content="{'a': 2,}", metadata={"content_type": "application/json"}
    )
    out = await middleware.process(response, "sid", {})
    assert out.metadata.get("repaired") is True
    assert out.content == '{"a": 2}'
