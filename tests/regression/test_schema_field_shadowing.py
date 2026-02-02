"""
Regression test for Pydantic schema field shadowing issue.

Issue: Field name "schema" in "StructuredOutputContext" shadows an attribute in parent "BaseModel".
This caused a UserWarning during server startup.

Resolution: Renamed field from "schema" to "response_schema" to avoid shadowing.

This test ensures the field works correctly and doesn't shadow BaseModel attributes.
"""

import warnings
from typing import Any

from src.core.domain.backend_request_manager.context_models import (
    StructuredOutputContext,
)


class TestSchemaFieldShadowingRegression:
    """Regression tests for GH-XXX: schema field shadowing BaseModel attribute."""

    def test_no_pydantic_shadowing_warning_on_model_creation(self) -> None:
        """
        Test that creating StructuredOutputContext doesn't trigger Pydantic shadowing warning.

        The original bug caused this warning:
        UserWarning: Field name "schema" in "StructuredOutputContext" shadows an attribute in parent "BaseModel"
        """
        schema_data: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

        # Capture all warnings during model instantiation
        with warnings.catch_warnings(record=True) as warning_list:
            warnings.simplefilter("always")

            context = StructuredOutputContext(
                response_schema=schema_data,
                schema_name="test_schema",
                request_id="req-123",
            )

            # Check that no shadowing warning was emitted
            shadowing_warnings = [
                w
                for w in warning_list
                if issubclass(w.category, UserWarning)
                and "shadows an attribute in parent" in str(w.message)
                and "schema" in str(w.message)
            ]

            assert len(shadowing_warnings) == 0, (
                f"Pydantic shadowing warning detected: {shadowing_warnings[0].message}"
                if shadowing_warnings
                else ""
            )

            # Verify the model was created correctly
            assert context.response_schema == schema_data
            assert context.schema_name == "test_schema"
            assert context.request_id == "req-123"

    def test_response_schema_field_accessible(self) -> None:
        """
        Test that the response_schema field is accessible and returns the expected value.

        This ensures the renamed field works correctly after the fix.
        """
        schema_data = {"type": "object", "required": ["id"]}

        context = StructuredOutputContext(
            response_schema=schema_data,
            schema_name="my_schema",
            request_id="req-456",
        )

        # Verify field access works
        assert context.response_schema == schema_data
        assert isinstance(context.response_schema, dict)
        assert context.response_schema["type"] == "object"

    def test_basemodel_schema_method_still_works(self) -> None:
        """
        Test that BaseModel's schema() method is still accessible and not shadowed.

        The original issue was that our 'schema' field shadowed BaseModel.schema() method.
        After renaming to 'response_schema', the BaseModel.schema() should work.
        """
        context = StructuredOutputContext(
            response_schema={"type": "string"},
            schema_name="simple_schema",
            request_id="req-789",
        )

        # BaseModel.schema() should return the JSON schema of the model itself
        model_schema = context.model_json_schema()

        # Verify the model schema is accessible and valid
        assert isinstance(model_schema, dict)
        assert "properties" in model_schema
        assert "response_schema" in model_schema["properties"]
        assert "schema_name" in model_schema["properties"]
        assert "request_id" in model_schema["properties"]

        # Verify 'schema' is NOT in the properties (it was renamed to 'response_schema')
        assert "schema" not in model_schema["properties"]

    def test_complex_schema_stored_correctly(self) -> None:
        """
        Test that complex JSON schemas are stored and retrieved correctly.

        This validates the fix works with real-world schema structures.
        """
        complex_schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer", "minimum": 0},
                        "email": {"type": "string", "format": "email"},
                    },
                    "required": ["name", "email"],
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["user", "items"],
        }

        context = StructuredOutputContext(
            response_schema=complex_schema,
            schema_name="complex_user_schema",
            request_id="req-complex-001",
        )

        # Verify the complex schema is preserved
        assert context.response_schema == complex_schema
        assert context.response_schema["type"] == "object"
        assert "properties" in context.response_schema
        assert "user" in context.response_schema["properties"]

    def test_model_dump_includes_response_schema(self) -> None:
        """
        Test that model_dump() correctly includes the response_schema field.

        This ensures serialization works correctly after the field rename.
        """
        schema_data = {"type": "boolean"}

        context = StructuredOutputContext(
            response_schema=schema_data,
            schema_name="boolean_schema",
            request_id="req-dump-001",
        )

        # Serialize to dict
        dumped = context.model_dump()

        # Verify all fields are present
        assert "response_schema" in dumped
        assert "schema_name" in dumped
        assert "request_id" in dumped

        # Verify values are correct
        assert dumped["response_schema"] == schema_data
        assert dumped["schema_name"] == "boolean_schema"
        assert dumped["request_id"] == "req-dump-001"

        # Verify 'schema' is NOT in the dumped data (it was renamed)
        assert "schema" not in dumped

    def test_model_serialization_roundtrip(self) -> None:
        """
        Test that serialization and deserialization work correctly.

        This validates the model can be serialized to JSON and back.
        """
        import json

        original_schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive"]}
            },
        }

        context = StructuredOutputContext(
            response_schema=original_schema,
            schema_name="status_schema",
            request_id="req-roundtrip-001",
        )

        # Serialize to JSON string
        json_str = context.model_dump_json()

        # Parse back to dict
        parsed = json.loads(json_str)

        # Create new instance from parsed data
        restored = StructuredOutputContext(**parsed)

        # Verify roundtrip preserved all data
        assert restored.response_schema == original_schema
        assert restored.schema_name == "status_schema"
        assert restored.request_id == "req-roundtrip-001"
