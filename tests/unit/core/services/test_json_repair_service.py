from __future__ import annotations

import pytest
from src.core.services.json_repair_service import JsonRepairService


@pytest.fixture
def json_repair_service() -> JsonRepairService:
    return JsonRepairService()


def test_repair_json_valid(json_repair_service: JsonRepairService) -> None:
    assert json_repair_service.repair_json('{"a": 1}') == {"a": 1}


def test_repair_json_invalid(json_repair_service: JsonRepairService) -> None:
    assert json_repair_service.repair_json("{'a': 1,}") == {"a": 1}


def test_validate_json_valid(json_repair_service: JsonRepairService) -> None:
    json_repair_service.validate_json({"a": 1}, {"type": "object"})


def test_validate_json_invalid(json_repair_service: JsonRepairService) -> None:
    from jsonschema.exceptions import ValidationError

    with pytest.raises(ValidationError):
        json_repair_service.validate_json(
            {"a": "1"}, {"type": "object", "properties": {"a": {"type": "number"}}}
        )


def test_repair_and_validate_json_non_strict_handles_schema_error(
    json_repair_service: JsonRepairService,
) -> None:
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    result = json_repair_service.repair_and_validate_json(
        '{"a": "1"}', schema=schema, strict=False
    )
    assert result is None
