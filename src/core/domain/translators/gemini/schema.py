from __future__ import annotations

from typing import Any


def sanitize_gemini_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitize OpenAI tool JSON schema for Gemini Code Assist function_declarations.

    The Code Assist API (when routing to Claude models) rejects certain JSON Schema
    keywords that don't conform to JSON Schema draft 2020-12. This method removes
    unsupported keywords while preserving the core shape (type, properties, required,
    items, enum, etc.).

    This is critical for compatibility with clients like Droid/Factory CLI that may
    send tool definitions with non-standard or draft-specific schema fields.
    """
    if not isinstance(schema, dict):
        return {}

    blacklist = {
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
            if parent_key == "properties":
                return {k: _clean(v, parent_key=None) for k, v in obj.items()}

            cleaned: dict[str, Any] = {}

            type_value = obj.get("type")
            if isinstance(type_value, list):
                non_null_types = [t for t in type_value if t != "null"]
                has_null = "null" in type_value

                if non_null_types:
                    cleaned["type"] = non_null_types[0]
                else:
                    cleaned["type"] = "string"

                if has_null:
                    cleaned["nullable"] = True

            for key in ["anyOf", "oneOf"]:
                if key in obj and isinstance(obj[key], list) and obj[key]:
                    first_option = _clean(obj[key][0], parent_key=key)
                    if isinstance(first_option, dict):
                        cleaned.update(first_option)
                    break

            for k, v in obj.items():
                if k in blacklist:
                    continue

                if k == "type" and isinstance(v, list):
                    continue

                if k in ["anyOf", "oneOf"]:
                    continue

                if k == "items" and isinstance(v, list):
                    cleaned[k] = {}
                    continue

                cleaned[k] = _clean(v, parent_key=k)
            return cleaned

        if isinstance(obj, list):
            return [_clean(x, parent_key=parent_key) for x in obj]
        return obj

    def _validate_required(obj: dict[str, Any]) -> dict[str, Any]:
        """Ensure 'required' array only references properties that exist."""
        if not isinstance(obj, dict):
            return obj

        properties = obj.get("properties")
        required = obj.get("required")

        if isinstance(properties, dict) and isinstance(required, list):
            valid_required = [
                prop_name
                for prop_name in required
                if isinstance(prop_name, str) and prop_name in properties
            ]
            if valid_required:
                obj["required"] = valid_required
            else:
                obj.pop("required", None)

        if isinstance(properties, dict):
            for prop_name, prop_schema in properties.items():
                if isinstance(prop_schema, dict):
                    properties[prop_name] = _validate_required(prop_schema)

        items = obj.get("items")
        if isinstance(items, dict):
            obj["items"] = _validate_required(items)

        return obj

    cleaned = _clean(schema)
    if isinstance(cleaned, dict):
        cleaned = _validate_required(cleaned)
    return cleaned if isinstance(cleaned, dict) else {}
