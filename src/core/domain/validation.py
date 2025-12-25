from __future__ import annotations

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
