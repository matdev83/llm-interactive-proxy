from __future__ import annotations

import json
import logging
from typing import Any, cast

from json_repair import repair_json
from jsonschema import validate

logger = logging.getLogger(__name__)


class JsonRepairService:
    """
    A service to repair and validate JSON data.
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
        except (ValueError, TypeError) as e:
            if strict:
                raise e
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
