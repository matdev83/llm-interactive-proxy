from __future__ import annotations

from typing import Any, cast


def _sanitize_gemini_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitize OpenAI tool JSON schema for Gemini Code Assist function_declarations.

    The Code Assist API (when routing to Claude models) rejects certain JSON Schema
    keywords that don't conform to JSON Schema draft 2020-12. This removes unsupported
    keywords while preserving core structure.
    """

    if not isinstance(schema, dict):
        return {}

    blacklist: set[str] = {
        "$schema",
        "$id",
        "$comment",
        "$defs",
        "definitions",
        "$ref",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "additionalProperties",
        "format",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "strict",
        "title",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "const",
        "contentMediaType",
        "contentEncoding",
    }

    def _clean(obj: Any, *, parent_key: str | None = None) -> Any:
        if isinstance(obj, dict):
            if "anyOf" in obj and isinstance(obj["anyOf"], list) and obj["anyOf"]:
                chosen = obj["anyOf"][0]
                merged: dict[str, Any] = (
                    dict(chosen) if isinstance(chosen, dict) else {}
                )
                if obj.get("description") is not None:
                    merged["description"] = obj["description"]
                return _clean(merged, parent_key=parent_key)

            if "oneOf" in obj and isinstance(obj["oneOf"], list) and obj["oneOf"]:
                chosen = obj["oneOf"][0]
                merged = dict(chosen) if isinstance(chosen, dict) else {}
                if obj.get("description") is not None:
                    merged["description"] = obj["description"]
                return _clean(merged, parent_key=parent_key)

            if "allOf" in obj and isinstance(obj["allOf"], list) and obj["allOf"]:
                chosen = obj["allOf"][0]
                merged = dict(chosen) if isinstance(chosen, dict) else {}
                if obj.get("description") is not None:
                    merged["description"] = obj["description"]
                return _clean(merged, parent_key=parent_key)

            if parent_key == "properties":
                return {
                    key: _clean(value, parent_key=None) for key, value in obj.items()
                }

            cleaned: dict[str, Any] = {}
            for key, value in obj.items():
                if key in blacklist:
                    continue
                if key == "items" and isinstance(value, list):
                    cleaned["items"] = {}
                    continue
                cleaned[key] = _clean(value, parent_key=key)

            if cleaned.get("type") == "object" and isinstance(
                cleaned.get("properties"), dict
            ):
                required_value = cleaned.get("required")
                if isinstance(required_value, list):
                    properties = cleaned["properties"]
                    valid_required = [
                        item
                        for item in required_value
                        if isinstance(item, str) and item in properties
                    ]
                    if valid_required:
                        cleaned["required"] = valid_required
                    else:
                        cleaned.pop("required", None)

            return cleaned

        if isinstance(obj, list):
            return [_clean(item, parent_key=parent_key) for item in obj]

        return obj

    return cast(dict[str, Any], _clean(schema))
