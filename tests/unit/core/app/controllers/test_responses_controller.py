"""Unit tests for the ResponsesController front-end logic."""

import pytest
from src.core.app.controllers.responses_controller import ResponsesController


class TestResponsesControllerSchemaValidation:
    """Tests covering JSON schema validation helper logic."""

    def test_validate_json_schema_allows_ref_only_properties(self) -> None:
        """Ensure properties that rely on $ref do not raise validation errors."""

        schema = {
            "type": "object",
            "properties": {
                "user": {"$ref": "#/$defs/user"},
            },
            "$defs": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }
            },
        }

        # Should not raise an exception
        ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_requires_type_or_structure(self) -> None:
        """Properties without type or structural keywords should be rejected."""

        schema = {
            "type": "object",
            "properties": {
                "invalid": {},
            },
        }

        with pytest.raises(ValueError):
            ResponsesController._validate_json_schema(schema)

    def test_validate_json_schema_accepts_union_type_and_items_list(self) -> None:
        """Union-typed schemas with list-based items should validate successfully."""

        schema = {
            "type": ["object", "null"],
            "properties": {
                "values": {
                    "type": ["array", "null"],
                    "items": [{"type": "string"}],
                }
            },
            "additionalProperties": False,
        }

        # Should not raise a TypeError or validation error
        ResponsesController._validate_json_schema(schema)
