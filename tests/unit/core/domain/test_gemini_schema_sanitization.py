from src.core.domain.translation import Translation


class TestGeminiSchemaSanitization:
    """Tests for Gemini Code Assist tool schema sanitization."""

    def test_sanitize_removes_schema_field(self):
        """Test that the $schema field is removed from the schema."""
        schema = {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
            "$schema": "http://json-schema.org/draft-07/schema#",
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        assert "$schema" not in cleaned
        assert cleaned["type"] == "object"
        assert "foo" in cleaned["properties"]

    def test_sanitize_converts_tuple_items_to_empty_schema(self):
        """Test that array items with tuple validation are converted to empty schema."""
        # This was the specific issue causing 400 INVALID_ARGUMENT
        schema = {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": [
                        {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                            },
                            "required": ["content", "status"],
                            "additionalProperties": False,
                        },
                        {"type": "string"},
                    ],
                    "description": "The updated todo list",
                }
            },
            "required": ["todos"],
            "additionalProperties": False,
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        todos_prop = cleaned["properties"]["todos"]
        assert todos_prop["type"] == "array"
        assert "items" in todos_prop

        # Verify conversion to empty schema {} (allow anything)
        items = todos_prop["items"]
        assert items == {}
        assert "anyOf" not in items

    def test_sanitize_preserves_standard_items(self):
        """Test that standard homogeneous array items are preserved."""
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        tags_prop = cleaned["properties"]["tags"]
        assert tags_prop["type"] == "array"
        assert isinstance(tags_prop["items"], dict)
        assert tags_prop["items"]["type"] == "string"
        assert "anyOf" not in tags_prop["items"]

    def test_sanitize_nested_tuple_items(self):
        """Test that nested tuple items are also converted to empty schema."""
        schema = {
            "type": "object",
            "properties": {
                "matrix": {
                    "type": "array",
                    "items": [
                        {
                            "type": "array",
                            "items": [{"type": "string"}, {"type": "integer"}],
                        }
                    ],
                }
            },
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        matrix_prop = cleaned["properties"]["matrix"]
        # Outer array was a tuple [array], so it becomes empty schema
        assert matrix_prop["items"] == {}

    def test_sanitize_flattens_unions(self):
        """Test that anyOf/oneOf unions are flattened by picking the first option."""
        schema = {
            "type": "object",
            "properties": {
                "union_field": {
                    "anyOf": [
                        {"type": "string", "description": "A string option"},
                        {"type": "integer", "description": "An integer option"},
                    ],
                    "description": "A union field",
                }
            },
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)
        field = cleaned["properties"]["union_field"]

        # Should have picked the first option (string)
        assert field["type"] == "string"
        # Should preserve description from the union container
        assert field["description"] == "A union field"
        # Should NOT have anyOf
        assert "anyOf" not in field

    def test_sanitize_preserves_property_named_pattern(self):
        """Preserve properties whose names match stripped schema keywords.

        The sanitizer must remove JSON Schema constraint keywords like "pattern" from
        property schemas, but must not delete a tool parameter named "pattern".
        """
        schema = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern",
                    "minLength": 1,
                },
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        assert "pattern" in cleaned["properties"]
        assert cleaned["properties"]["pattern"]["type"] == "string"
        assert "minLength" not in cleaned["properties"]["pattern"]
        assert cleaned["required"] == ["pattern", "path"]

    def test_sanitize_converts_properties_map_list(self):
        """Convert key/value property lists into a properties dict."""
        schema = {
            "type": "object",
            "properties": [
                {"key": "path", "value": {"type": "string"}},
                {
                    "key": "options",
                    "value": {
                        "type": "object",
                        "properties": [
                            {"key": "recursive", "value": {"type": "boolean"}},
                            {"key": "depth", "value": {"type": "integer"}},
                        ],
                        "required": ["recursive", "depth"],
                    },
                },
            ],
            "required": ["path", "options"],
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        assert isinstance(cleaned.get("properties"), dict)
        assert cleaned["properties"]["path"]["type"] == "string"
        assert cleaned["properties"]["options"]["type"] == "object"
        assert (
            cleaned["properties"]["options"]["properties"]["recursive"]["type"]
            == "boolean"
        )
        assert cleaned["required"] == ["path", "options"]

    def test_sanitize_drops_invalid_properties_list(self):
        """Fallback to empty properties when list cannot be coerced."""
        schema = {
            "type": "object",
            "properties": [{"value": {"type": "string"}}],
            "required": ["path"],
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        assert cleaned["properties"] == {}

    def test_sanitize_coerces_type_list_to_single(self):
        """Union types should be coerced to a single Gemini-compatible type."""
        schema = {
            "type": "object",
            "properties": {"value": {"type": ["string", "null"]}},
        }

        cleaned = Translation._sanitize_gemini_parameters(schema)

        value_schema = cleaned["properties"]["value"]
        assert value_schema["type"] == "string"
        assert "nullable" not in value_schema

    def test_sanitize_adds_items_for_array_without_items(self):
        """Arrays should include items even if missing in input."""
        schema = {"type": "object", "properties": {"values": {"type": "array"}}}

        cleaned = Translation._sanitize_gemini_parameters(schema)

        values_schema = cleaned["properties"]["values"]
        assert values_schema["type"] == "array"
        assert values_schema["items"] == {}

    def test_sanitize_sets_object_type_when_missing(self):
        """Object schemas should have type=object when properties exist."""
        schema = {"properties": {"value": {"type": "string"}}}

        cleaned = Translation._sanitize_gemini_parameters(schema)

        assert cleaned["type"] == "object"
