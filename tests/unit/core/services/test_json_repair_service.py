from __future__ import annotations

import pytest
from src.core.common.exceptions import JSONParsingError, ValidationError
from src.core.services.json_repair_service import (
    MAX_SCHEMA_COLLECTION_ITEMS,
    MAX_SCHEMA_PROPERTIES,
    JsonRepairService,
    enforce_schema_size_limits,
)


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


def test_enforce_schema_size_limits_rejects_excessive_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            f"field_{i}": {"type": "string"}
            for i in range(MAX_SCHEMA_PROPERTIES + 1)
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        enforce_schema_size_limits(schema)

    assert "too many properties" in str(exc_info.value)


def test_enforce_schema_size_limits_rejects_large_collections() -> None:
    schema = {
        "type": "object",
        "properties": {
            "numbers": {
                "type": "array",
                "items": {"type": "number"},
                "enum": list(range(MAX_SCHEMA_COLLECTION_ITEMS + 1)),
            }
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        enforce_schema_size_limits(schema)

    assert "collection" in str(exc_info.value)
