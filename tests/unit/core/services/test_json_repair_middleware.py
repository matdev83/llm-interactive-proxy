from __future__ import annotations

import pytest
from src.core.app.middleware.json_repair_middleware import JsonRepairMiddleware
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.json_repair_service import JsonRepairService


@pytest.fixture
def json_repair_service() -> JsonRepairService:
    return JsonRepairService()


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(
        session=SessionConfig(
            json_repair_enabled=True,
            json_repair_strict_mode=False,
        )
    )


@pytest.fixture
def json_repair_middleware(
    config: AppConfig, json_repair_service: JsonRepairService
) -> JsonRepairMiddleware:
    return JsonRepairMiddleware(config, json_repair_service)


async def test_process_response_valid(
    json_repair_middleware: JsonRepairMiddleware,
) -> None:
    response = ProcessedResponse(content='{"a": 1}')
    processed_response = await json_repair_middleware.process(
        response, "session_id", {}
    )
    assert processed_response.content == '{"a": 1}'
    assert processed_response.metadata.get("repaired")


async def test_process_response_invalid(
    json_repair_middleware: JsonRepairMiddleware,
) -> None:
    response = ProcessedResponse(content="{'a': 1,}")
    processed_response = await json_repair_middleware.process(
        response, "session_id", {}
    )
    assert processed_response.content == '{"a": 1}'
    assert processed_response.metadata.get("repaired")
