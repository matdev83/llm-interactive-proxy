"""
URI Parameter Validator Service

This module provides validation and normalization for URI parameters
extracted from model strings.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic.types import JsonValue

logger = logging.getLogger(__name__)


class URIParameterValidationResult(BaseModel):
    """Result of URI parameter validation and normalization.

    Attributes:
        normalized_params: Dict with validated and type-converted parameters.
            Values must be JSON-serializable (JsonValue).
        validation_errors: List of error messages for invalid parameters.
    """

    normalized_params: dict[str, JsonValue] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)


class URIParameterValidator:
    """Validates and normalizes URI parameters from model strings."""

    # Supported parameters with their validation rules
    SUPPORTED_PARAMS: dict[str, dict[str, Any]] = {
        "temperature": {
            "type": float,
            "min": 0.0,
            "max": 2.0,
            "description": "Controls randomness in model outputs",
        },
        "reasoning_effort": {
            "type": str,
            "allowed": ["low", "medium", "high", "xhigh", "max"],
            "description": (
                "Controls computational effort for reasoning (includes provider-specific "
                "levels such as xhigh and max where the upstream API supports them)"
            ),
        },
        "top_p": {
            "type": float,
            "min": 0.0,
            "max": 1.0,
            "description": "Controls nucleus sampling probability mass",
        },
        "top_k": {
            "type": int,
            "min": 1,
            "description": "Controls top-k sampling candidate count",
        },
    }

    def validate_and_normalize(
        self, params: dict[str, Any]
    ) -> tuple[dict[str, JsonValue], list[str]]:
        """
        Validate and normalize URI parameters.

        Args:
            params: Raw URI parameters extracted from model string

        Returns:
            Tuple of (normalized_params, validation_errors)
            - normalized_params: Dict with validated and type-converted parameters
            - validation_errors: List of error messages for invalid parameters

        Examples:
            >>> validator = URIParameterValidator()
            >>> normalized, errors = validator.validate_and_normalize({"temperature": "0.5"})
            >>> normalized
            {"temperature": 0.5}
            >>> errors
            []

            >>> normalized, errors = validator.validate_and_normalize({"top_p": "0.9", "top_k": "40"})
            >>> normalized
            {"top_p": 0.9, "top_k": 40}

            >>> normalized, errors = validator.validate_and_normalize({"temperature": "3.5"})
            >>> normalized
            {}
            >>> errors
            ["temperature: 3.5 out of valid range (0.0-2.0)"]

            >>> normalized, errors = validator.validate_and_normalize({"unknown_param": "value"})
            >>> normalized
            {}
            >>> errors
            []  # Unknown params logged as warning, not error
        """
        normalized_params: dict[str, JsonValue] = {}
        validation_errors: list[str] = []

        for param_name, param_value in params.items():
            # Check if parameter is supported
            if param_name not in self.SUPPORTED_PARAMS:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Unknown URI parameter '{param_name}' with value '{param_value}'. "
                        f"Supported parameters: {', '.join(self.SUPPORTED_PARAMS.keys())}"
                    )
                continue
            # Get validation rules for this parameter
            rules = self.SUPPORTED_PARAMS[param_name]
            param_type = rules["type"]

            try:
                # Type conversion and validation
                normalized_value: float | str | int
                if param_type is float:
                    normalized_value = self._validate_float_param(
                        param_name, param_value, rules
                    )
                elif param_type is str:
                    normalized_value = self._validate_string_param(
                        param_name, param_value, rules
                    )
                elif param_type is int:
                    normalized_value = self._validate_int_param(
                        param_name, param_value, rules
                    )
                else:
                    # Unsupported type in rules (should not happen)
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            f"Unsupported parameter type '{param_type}' for '{param_name}'"
                        )
                    validation_errors.append(
                        f"{param_name}: unsupported parameter type"
                    )
                    continue

                # Add to normalized params if validation passed
                normalized_params[param_name] = normalized_value

            except ValueError as e:
                # Validation failed - log error and add to error list
                error_msg = str(e)
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Invalid URI parameter value: {param_name}={param_value}. {error_msg}",
                        exc_info=True,
                    )
                validation_errors.append(f"{param_name}: {error_msg}")

        return (normalized_params, validation_errors)

    def _validate_float_param(
        self, param_name: str, param_value: Any, rules: dict[str, Any]
    ) -> float:
        """
        Validate and convert a float parameter.

        Args:
            param_name: Name of the parameter
            param_value: Raw value from URI
            rules: Validation rules for this parameter

        Returns:
            Validated float value

        Raises:
            ValueError: If validation fails
        """
        # Convert to float
        try:
            float_value = float(param_value)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"must be a valid number, got '{param_value}' ({type(param_value).__name__})"
            ) from e

        # Check range
        min_val = rules.get("min")
        max_val = rules.get("max")

        if min_val is not None and float_value < min_val:
            raise ValueError(f"{float_value} below minimum value ({min_val})")

        if max_val is not None and float_value > max_val:
            raise ValueError(f"{float_value} above maximum value ({max_val})")

        return float_value

    def _validate_int_param(
        self, param_name: str, param_value: Any, rules: dict[str, Any]
    ) -> int:
        """Validate and convert an integer parameter."""

        try:
            if isinstance(param_value, float):
                if not param_value.is_integer():
                    raise ValueError(f"must be a whole number, got '{param_value}'")
                int_value = int(param_value)
            elif isinstance(param_value, int):
                int_value = param_value
            else:
                # Attempt to parse from string-like representations
                string_value = str(param_value).strip()
                float_value = float(string_value)
                if not float_value.is_integer():
                    raise ValueError(f"must be a whole number, got '{param_value}'")
                int_value = int(float_value)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"must be a whole number, got '{param_value}' ({type(param_value).__name__})"
            ) from exc

        min_val = rules.get("min")
        max_val = rules.get("max")

        if min_val is not None and int_value < int(min_val):
            raise ValueError(f"{int_value} below minimum value ({min_val})")

        if max_val is not None and int_value > int(max_val):
            raise ValueError(f"{int_value} above maximum value ({max_val})")

        return int_value

    def _validate_string_param(
        self, param_name: str, param_value: Any, rules: dict[str, Any]
    ) -> str:
        """
        Validate a string parameter.

        Args:
            param_name: Name of the parameter
            param_value: Raw value from URI
            rules: Validation rules for this parameter

        Returns:
            Validated string value

        Raises:
            ValueError: If validation fails
        """
        # Convert to string
        str_value = str(param_value)

        # Check allowed values
        allowed = rules.get("allowed")
        if allowed is not None and str_value not in allowed:
            raise ValueError(
                f"'{str_value}' not in allowed values: {', '.join(allowed)}"
            )

        return str_value
