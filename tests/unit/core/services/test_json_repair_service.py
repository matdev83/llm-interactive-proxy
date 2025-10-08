from __future__ import annotations

import pytest
from src.core.common.exceptions import JSONParsingError, ValidationError
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


def test_repair_and_validate_json_schema_failure_best_effort(
    json_repair_service: JsonRepairService,
) -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "required": ["a"],
    }

    repaired = json_repair_service.repair_and_validate_json(
        '{"a": "text"}', schema=schema, strict=False
    )

    assert repaired is None


def test_repair_and_validate_json_schema_failure_strict(
    json_repair_service: JsonRepairService,
) -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "required": ["a"],
    }

    with pytest.raises(ValidationError) as exc_info:
        json_repair_service.repair_and_validate_json(
            '{"a": "text"}', schema=schema, strict=True
        )

    assert "JSON does not match required schema" in str(exc_info.value)


def test_repair_and_validate_json_parse_failure_strict(
    json_repair_service: JsonRepairService,
) -> None:
    with pytest.raises(JSONParsingError):
        json_repair_service.repair_and_validate_json("not-json", strict=True)


def test_validate_response_schema_allows_boolean_subschemas(
    json_repair_service: JsonRepairService,
) -> None:
    schema = {
        "type": "object",
        "properties": {
            "any_value": True,
            "forbidden": False,
            "typed": {"type": "string"},
        },
    }

    assert json_repair_service.validate_response_schema(schema)
