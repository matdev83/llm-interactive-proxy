from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


class ValidationResult(DomainModel):
    """Result of a validation operation."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)

    @classmethod
    def success(cls) -> ValidationResult:
        """Create a successful validation result."""
        return cls(is_valid=True, errors=[])

    @classmethod
    def failure(cls, errors: list[str] | str) -> ValidationResult:
        """Create a failed validation result."""
        if isinstance(errors, str):
            errors = [errors]
        return cls(is_valid=False, errors=errors)

    def __bool__(self) -> bool:
        """Allow using the result in boolean contexts."""
        return self.is_valid


@dataclass(frozen=True)
class BackendModelValidation:
    """Result of backend and model validation.

    Represents whether a backend and model combination is valid,
    along with an optional error message if invalid.
    """

    is_valid: bool
    error_message: str | None = None

    @classmethod
    def valid(cls) -> BackendModelValidation:
        """Create a valid validation result."""
        return cls(is_valid=True, error_message=None)

    @classmethod
    def invalid(cls, error_message: str) -> BackendModelValidation:
        """Create an invalid validation result with an error message."""
        return cls(is_valid=False, error_message=error_message)


@dataclass(frozen=True)
class SchemaValidationResult:
    """Result of JSON schema validation.

    Represents whether JSON data validates against a schema,
    along with an optional error message if invalid.
    """

    is_valid: bool
    error_message: str | None = None

    @classmethod
    def valid(cls) -> SchemaValidationResult:
        """Create a valid validation result."""
        return cls(is_valid=True, error_message=None)

    @classmethod
    def invalid(cls, error_message: str) -> SchemaValidationResult:
        """Create an invalid validation result with an error message."""
        return cls(is_valid=False, error_message=error_message)


@dataclass(frozen=True)
class FailoverElementValidation:
    """Result of parsing and validating a failover route element.

    Represents the validated element string and optional warning message.
    """

    validated_element: str | None
    warning: str | None = None

    @classmethod
    def valid(
        cls, element: str, warning: str | None = None
    ) -> FailoverElementValidation:
        """Create a valid validation result with optional warning."""
        return cls(validated_element=element, warning=warning)

    @classmethod
    def invalid(cls, warning: str) -> FailoverElementValidation:
        """Create an invalid validation result with a warning."""
        return cls(validated_element=None, warning=warning)
