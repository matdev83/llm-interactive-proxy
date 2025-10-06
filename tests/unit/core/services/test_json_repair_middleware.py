from __future__ import annotations

from typing import Any

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


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


async def test_process_response_empty_object(
    json_repair_middleware: JsonRepairMiddleware,
) -> None:
    response = ProcessedResponse(content="{}")
    processed_response = await json_repair_middleware.process(
        response, "session_id", {}
    )

    assert processed_response.content == "{}"
    assert processed_response.metadata.get("repaired") is True


async def test_process_response_best_effort_failure_metrics(
    json_repair_middleware: JsonRepairMiddleware,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metric_calls: list[str] = []

    def fake_inc(metric_name: str) -> None:
        metric_calls.append(metric_name)

    monkeypatch.setattr(
        "src.core.app.middleware.json_repair_middleware.metrics.inc",
        fake_inc,
    )

    def fail_repair(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("repair boom")

    monkeypatch.setattr(
        json_repair_middleware.json_repair_service,
        "repair_and_validate_json",
        fail_repair,
    )

    response = ProcessedResponse(content="{'broken': true}")

    with pytest.raises(RuntimeError):
        await json_repair_middleware.process(response, "session_id", {})

    assert metric_calls
    assert metric_calls[-1] == "json_repair.non_streaming.best_effort_fail"
