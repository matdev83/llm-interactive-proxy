from __future__ import annotations

import json
import logging
from typing import Any, cast

from json_repair import repair_json
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate

from src.core.common.exceptions import JSONParsingError, ValidationError

logger = logging.getLogger(__name__)


class JsonRepairService:
    """
    A service to repair and validate JSON data.
    Extended to support Responses API schema validation and integration
    with existing response processing middleware.
    """

    def repair_and_validate_json(
        self,
        json_string: str,
        schema: dict[str, Any] | None = None,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        """
        Repairs a JSON string and optionally validates it against a schema.

        Args:
            json_string: The JSON string to repair and validate.
            schema: The JSON schema to validate against.
            strict: If True, raises an error if the JSON is invalid after repair.

        Returns:
            The repaired and validated JSON object, or None if repair fails.
        """
        try:
            repaired_json = self.repair_json(json_string)
            if schema:
                self.validate_json(repaired_json, schema)
            return repaired_json
        except JsonSchemaValidationError as e:
            if strict:
                raise ValidationError(
                    message=f"JSON does not match required schema: {e.message}",
                    details={
                        "schema_path": list(e.absolute_path)
                        if getattr(e, "absolute_path", None)
                        else [],
                        "schema": getattr(e, "schema", None),
                        "failed_value": getattr(e, "instance", None),
                    },
                ) from e
            logger.warning("JSON schema validation failed: %s", e)
            return None
        except (ValueError, TypeError) as e:
            if strict:
                raise JSONParsingError(
                    message=f"Failed to repair JSON content: {e}",
                    details={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                ) from e
            logger.warning(f"Failed to repair or validate JSON: {e}")
            return None

    def repair_json(self, json_string: str) -> dict[str, Any]:
        """
        Repairs a JSON string.

        Args:
            json_string: The JSON string to repair.

        Returns:
            The repaired JSON object.
        """
        repaired_string = repair_json(json_string)
        return cast(dict[str, Any], json.loads(repaired_string))

    def validate_json(
        self, json_object: dict[str, Any], schema: dict[str, Any]
    ) -> None:
        """
        Validates a JSON object against a schema.

        Args:
            json_object: The JSON object to validate.
            schema: The JSON schema to validate against.
        """
        validate(instance=json_object, schema=schema)

    def process_structured_response(
        self,
        content: str,
        schema: dict[str, Any],
        session_id: str,
        strict: bool = True,
    ) -> tuple[str, dict[str, Any] | None]:
        """
        Process a response for structured output validation and repair.

        This method integrates with the existing response processing pipeline
        to handle Responses API schema validation requirements.

        Args:
            content: The response content to process
            schema: The JSON schema to validate against
            session_id: Session identifier for logging
            strict: Whether to enforce strict validation

        Returns:
            Tuple of (processed_content, parsed_object)
            - processed_content: The content as a string (may be repaired)
            - parsed_object: The parsed and validated JSON object, or None if validation fails

        Raises:
            ValidationError: If strict=True and validation fails after repair attempts
            JSONParsingError: If JSON parsing fails completely
        """
        try:
            # First, try to parse the content as-is
            try:
                parsed_json = json.loads(content)
                logger.debug(f"Successfully parsed JSON for session {session_id}")
            except json.JSONDecodeError as e:
                logger.info(
                    f"Initial JSON parsing failed for session {session_id}, attempting repair: {e}"
                )
                # Attempt to repair the JSON
                try:
                    parsed_json = self.repair_json(content)
                    logger.info(f"Successfully repaired JSON for session {session_id}")
                except Exception as repair_error:
                    logger.error(
                        f"JSON repair failed for session {session_id}: {repair_error}"
                    )
                    if strict:
                        raise JSONParsingError(
                            message=f"Failed to parse or repair JSON content: {repair_error}",
                            details={
                                "session_id": session_id,
                                "original_error": str(e),
                                "repair_error": str(repair_error),
                                "content_preview": (
                                    content[:200] if len(content) > 200 else content
                                ),
                            },
                        ) from repair_error
                    return content, None

            # Validate against the schema
            try:
                self.validate_json(parsed_json, schema)
                logger.debug(f"Schema validation successful for session {session_id}")

                # Return the properly formatted JSON string and the parsed object
                formatted_content = json.dumps(parsed_json, ensure_ascii=False)
                return formatted_content, parsed_json

            except JsonSchemaValidationError as validation_error:
                logger.warning(
                    f"Schema validation failed for session {session_id}: {validation_error}"
                )

                if strict:
                    raise ValidationError(
                        message=f"Response does not match required schema: {validation_error.message}",
                        details={
                            "session_id": session_id,
                            "schema_path": (
                                list(validation_error.absolute_path)
                                if hasattr(validation_error, "absolute_path")
                                and validation_error.absolute_path
                                else []
                            ),
                            "failed_value": (
                                validation_error.instance
                                if hasattr(validation_error, "instance")
                                else None
                            ),
                            "schema_constraint": (
                                validation_error.schema
                                if hasattr(validation_error, "schema")
                                else None
                            ),
                            "validation_error": str(validation_error),
                        },
                    ) from validation_error

                # In non-strict mode, return the repaired JSON even if it doesn't match schema
                formatted_content = json.dumps(parsed_json, ensure_ascii=False)
                return formatted_content, None

        except (JSONParsingError, ValidationError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error processing structured response for session {session_id}: {e}"
            )
            if strict:
                raise JSONParsingError(
                    message=f"Unexpected error processing structured response: {e}",
                    details={
                        "session_id": session_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                ) from e
            return content, None

    def validate_response_schema(self, schema: dict[str, Any]) -> bool:
        """
        Validate that a JSON schema is well-formed for use with Responses API.

        Args:
            schema: The JSON schema to validate

        Returns:
            True if the schema is valid, False otherwise

        Raises:
            ValidationError: If the schema is invalid and contains critical issues
        """
        try:
            # Basic schema structure validation
            if not isinstance(schema, dict):
                raise ValidationError(
                    message="Schema must be a dictionary",
                    details={"provided_type": type(schema).__name__},
                )

            # Check for required fields
            if "type" not in schema:
                raise ValidationError(
                    message="Schema must have a 'type' field",
                    details={"schema_keys": list(schema.keys())},
                )

            # Validate that it's a valid JSON schema by attempting to use it
            # We'll try to validate a simple test object against it
            test_object: dict[str, Any] = {}
            if schema.get("type") == "object" and "properties" in schema:
                for prop_name, prop_schema in schema.get("properties", {}).items():
                    if prop_schema.get("type") == "string":
                        test_object[prop_name] = "test"
                    elif prop_schema.get("type") == "number":
                        test_object[prop_name] = 0.0
                    elif prop_schema.get("type") == "boolean":
                        test_object[prop_name] = True
                    elif prop_schema.get("type") == "array":
                        test_object[prop_name] = []
                    elif prop_schema.get("type") == "object":
                        test_object[prop_name] = {}

            # Attempt validation to ensure schema is well-formed
            try:
                validate(instance=test_object, schema=schema)
            except JsonSchemaValidationError:
                # It's okay if the test object doesn't validate - we just want to ensure
                # the schema itself is well-formed enough for jsonschema to process
                pass
            except Exception as e:
                raise ValidationError(
                    message=f"Schema is malformed and cannot be used for validation: {e}",
                    details={
                        "schema": schema,
                        "validation_library_error": str(e),
                    },
                ) from e

            logger.debug("Schema validation successful")
            return True

        except ValidationError:
            # Re-raise our validation errors
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating schema: {e}")
            raise ValidationError(
                message=f"Unexpected error validating schema: {e}",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            ) from e
