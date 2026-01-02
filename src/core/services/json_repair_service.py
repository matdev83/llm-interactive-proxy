from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from json_repair import repair_json
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate

from src.core.common.exceptions import JSONParsingError, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonRepairResult:
    """Represents outcome of a JSON repair attempt."""

    success: bool
    content: Any | None


@dataclass(frozen=True)
class StructuredResponseProcessResult:
    """Represents outcome of structured response processing.

    Contains processed content string and optionally a parsed JSON object.
    """

    content: str
    parsed_object: dict[str, Any] | None

    # Make tuple unpacking work at call sites
    def __iter__(self):
        """Allow tuple unpacking for backward compatibility."""
        return iter((self.content, self.parsed_object))


# Upper bounds that keep schema validation fast while allowing reasonably
# complex schemas. These values can be tuned as needed but should remain well
# below the point where validating attacker-controlled schemas could exhaust
# CPU or memory resources.
MAX_SCHEMA_NODES = 5000
MAX_SCHEMA_COLLECTION_ITEMS = 1024
MAX_SCHEMA_PROPERTIES = 512

# Maximum JSON repair input size to prevent DoS attacks (1MB)
MAX_JSON_REPAIR_INPUT_SIZE = 1 * 1024 * 1024  # 1MB in bytes


def enforce_schema_size_limits(
    schema: dict[str, Any],
    *,
    max_nodes: int = MAX_SCHEMA_NODES,
    max_collection_items: int = MAX_SCHEMA_COLLECTION_ITEMS,
    max_properties: int = MAX_SCHEMA_PROPERTIES,
) -> None:
    """Ensure a JSON schema is not large enough to cause resource exhaustion."""

    if not isinstance(schema, dict):
        raise ValidationError(
            message="Schema must be a dictionary",
            details={"provided_type": type(schema).__name__},
        )

    nodes_seen = 0
    queue: deque[Any] = deque([schema])

    while queue:
        current = queue.pop()
        if isinstance(current, dict):
            nodes_seen += 1
            if nodes_seen > max_nodes:
                raise ValidationError(
                    message="JSON schema is too large",
                    details={
                        "max_nodes": max_nodes,
                    },
                )

            if len(current) > max_collection_items:
                raise ValidationError(
                    message="JSON schema object has too many keys",
                    details={
                        "max_items": max_collection_items,
                        "actual_items": len(current),
                    },
                )

            for key, value in current.items():
                if key == "properties" and isinstance(value, dict):
                    if len(value) > max_properties:
                        raise ValidationError(
                            message="JSON schema declares too many properties",
                            details={
                                "max_properties": max_properties,
                                "actual_properties": len(value),
                            },
                        )
                    queue.extend(value.values())
                elif isinstance(value, dict | list | tuple):
                    queue.append(value)
        elif isinstance(current, list | tuple):
            nodes_seen += 1
            if nodes_seen > max_nodes:
                raise ValidationError(
                    message="JSON schema is too large",
                    details={
                        "max_nodes": max_nodes,
                    },
                )

            if len(current) > max_collection_items:
                raise ValidationError(
                    message="JSON schema collection has too many entries",
                    details={
                        "max_items": max_collection_items,
                        "actual_items": len(current),
                    },
                )

            for item in current:
                if isinstance(item, dict | list | tuple):
                    queue.append(item)


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
    ) -> JsonRepairResult:
        """
        Repairs a JSON string and optionally validates it against a schema.

        Args:
            json_string: The JSON string to repair and validate.
            schema: The JSON schema to validate against.
            strict: If True, raises an error if the JSON is invalid after repair.

        Returns:
            JsonRepairResult describing whether repair succeeded and the content.
        """
        try:
            repaired_dict = self.repair_json(json_string)
            if schema is not None:
                enforce_schema_size_limits(schema)
                # repair_json already returns a dict, no need to parse again
                self.validate_json(repaired_dict, schema)
            return JsonRepairResult(success=True, content=repaired_dict)
        except JsonSchemaValidationError as e:
            if strict:
                raise ValidationError(
                    message=f"JSON does not match required schema: {e.message}",
                    details={
                        "schema_path": (
                            list(e.absolute_path)
                            if getattr(e, "absolute_path", None)
                            else []
                        ),
                        "schema": getattr(e, "schema", None),
                        "failed_value": getattr(e, "instance", None),
                    },
                ) from e
            logger.warning("JSON schema validation failed: %s", e)
            # repaired_dict may not be defined if exception occurred before assignment
            try:
                repaired_dict = self.repair_json(json_string)
            except (JSONParsingError, json.JSONDecodeError) as repair_error:
                # Expected exceptions from repair_json - log with context
                logger.warning(
                    "Failed to repair JSON after schema validation failure: %s",
                    repair_error,
                    exc_info=True,
                )
                repaired_dict = None
            except Exception as unexpected_error:
                # Unexpected exceptions during repair - log at warning level for visibility
                logger.warning(
                    "Unexpected error during JSON repair after schema validation failure: %s",
                    unexpected_error,
                    exc_info=True,
                )
                repaired_dict = None
            return JsonRepairResult(success=False, content=repaired_dict)
        except (ValueError, TypeError) as e:
            if strict:
                raise JSONParsingError(
                    message=f"Failed to repair JSON content: {e}",
                    details={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                ) from e
            logger.warning("Failed to repair or validate JSON: %s", e)
            return JsonRepairResult(success=False, content=None)

    def repair_json(self, json_string: str) -> Any:
        """
        Repairs a JSON string.

        Args:
            json_string: The JSON string to repair.

        Returns:
            The repaired JSON object.

        Raises:
            JSONParsingError: If input size exceeds limit or repair fails.
        """
        # DoS protection: Check input size before repair
        input_size = len(json_string.encode("utf-8"))
        if input_size > MAX_JSON_REPAIR_INPUT_SIZE:
            raise JSONParsingError(
                message=f"JSON string too large for repair ({input_size} bytes, limit: {MAX_JSON_REPAIR_INPUT_SIZE} bytes)",
                details={
                    "input_size": input_size,
                    "max_size": MAX_JSON_REPAIR_INPUT_SIZE,
                },
            )

        repaired_string = repair_json(json_string)
        return json.loads(repaired_string)

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
    ) -> StructuredResponseProcessResult:
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
            StructuredResponseProcessResult containing:
            - content: The content as a string (may be repaired)
            - parsed_object: The parsed and validated JSON object, or None if validation fails

        Raises:
            ValidationError: If strict=True and validation fails after repair attempts
            JSONParsingError: If JSON parsing fails completely
        """
        try:
            enforce_schema_size_limits(schema)
            # First, try to parse the content as-is
            try:
                parsed_json = json.loads(content)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Successfully parsed JSON for session {session_id}")
            except json.JSONDecodeError as e:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Initial JSON parsing failed for session {session_id}, attempting repair: {e}"
                    )
                # Attempt to repair the JSON
                try:
                    parsed_json = self.repair_json(content)
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            f"Successfully repaired JSON for session {session_id}"
                        )
                except (JSONParsingError, json.JSONDecodeError) as repair_error:
                    # Expected exceptions from repair_json - JSON parsing/repair failures
                    logger.error(
                        f"JSON repair failed for session {session_id}: {repair_error}",
                        exc_info=True,
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
                    return StructuredResponseProcessResult(
                        content=content, parsed_object=None
                    )
                except (MemoryError, OSError) as repair_error:
                    # System-level errors during repair - log with context
                    logger.error(
                        f"System error during JSON repair for session {session_id}: {repair_error}",
                        exc_info=True,
                    )
                    if strict:
                        raise JSONParsingError(
                            message=f"Failed to parse or repair JSON content due to system error: {repair_error}",
                            details={
                                "session_id": session_id,
                                "original_error": str(e),
                                "repair_error": str(repair_error),
                                "error_type": type(repair_error).__name__,
                                "content_preview": (
                                    content[:200] if len(content) > 200 else content
                                ),
                            },
                        ) from repair_error
                    return StructuredResponseProcessResult(
                        content=content, parsed_object=None
                    )
                except Exception as repair_error:
                    # Unexpected exceptions during repair - defensive guard for truly unexpected errors
                    logger.error(
                        f"Unexpected error during JSON repair for session {session_id}: {repair_error}",
                        exc_info=True,
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
                    return StructuredResponseProcessResult(
                        content=content, parsed_object=None
                    )

            # Validate against the schema
            try:
                self.validate_json(parsed_json, schema)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Schema validation successful for session {session_id}"
                    )

                # Return the properly formatted JSON string and the parsed object
                formatted_content = json.dumps(parsed_json, ensure_ascii=False)
                return StructuredResponseProcessResult(
                    content=formatted_content, parsed_object=parsed_json
                )

            except JsonSchemaValidationError as validation_error:
                if logger.isEnabledFor(logging.WARNING):
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
                return StructuredResponseProcessResult(
                    content=formatted_content, parsed_object=None
                )

        except (JSONParsingError, ValidationError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error processing structured response for session {session_id}: {e}",
                exc_info=True,
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
            return StructuredResponseProcessResult(content=content, parsed_object=None)

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
            enforce_schema_size_limits(schema)
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

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Schema validation successful")
            return True

        except ValidationError:
            # Re-raise our validation errors
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating schema: {e}", exc_info=True)
            raise ValidationError(
                message=f"Unexpected error validating schema: {e}",
                details={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            ) from e
