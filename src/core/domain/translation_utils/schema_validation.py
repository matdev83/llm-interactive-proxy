from __future__ import annotations

from typing import Any


def validate_json_against_schema(
    json_data: dict[str, Any], schema: dict[str, Any]
) -> tuple[bool, str | None]:
    """Validate JSON data against a JSON schema."""

    try:
        import jsonschema

        jsonschema.validate(json_data, schema)
        return True, None
    except ImportError:
        return basic_schema_validation(json_data, schema)
    except Exception as exc:
        if "jsonschema" in str(exc) and "ValidationError" in str(exc):
            return False, str(exc)
        return False, f"Schema validation error: {exc!s}"


def basic_schema_validation(
    json_data: dict[str, Any], schema: dict[str, Any]
) -> tuple[bool, str | None]:
    """Perform basic JSON schema validation without jsonschema library."""

    try:
        schema_type = schema.get("type")
        if schema_type == "object" and not isinstance(json_data, dict):
            return False, f"Expected object, got {type(json_data).__name__}"
        if schema_type == "array" and not isinstance(json_data, list):
            return False, f"Expected array, got {type(json_data).__name__}"
        if schema_type == "string" and not isinstance(json_data, str):
            return False, f"Expected string, got {type(json_data).__name__}"
        if schema_type == "number" and not isinstance(json_data, int | float):
            return False, f"Expected number, got {type(json_data).__name__}"
        if schema_type == "integer" and not isinstance(json_data, int):
            return False, f"Expected integer, got {type(json_data).__name__}"
        if schema_type == "boolean" and not isinstance(json_data, bool):
            return False, f"Expected boolean, got {type(json_data).__name__}"

        if schema_type == "object" and isinstance(json_data, dict):
            for prop in schema.get("required", []):
                if prop not in json_data:
                    return False, f"Missing required property: {prop}"

        return True, None
    except Exception as exc:
        return False, f"Basic validation error: {exc!s}"
