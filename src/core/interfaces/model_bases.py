"""Nominal marker base classes for model standardization.

Introduce `DomainModel` for Pydantic-based domain/API models and
`InternalDTO` for internal dataclass-based DTOs. Use these as
nominal markers so static type checkers (mypy) can enforce correct
usage across the codebase.
"""

from __future__ import annotations

from pydantic import BaseModel


class DomainModel(BaseModel):
    """Nominal marker for Pydantic-based domain and API models."""

    def __repr__(self) -> str:
        """Provide a concise, one-line summary of the object."""
        # Get the model's class name
        class_name = self.__class__.__name__

        # Attempt to find a unique identifier for a more informative repr
        # Common identifiers are 'id', 'name', or 'session_id'
        repr_attrs = ("id", "name", "session_id")
        for attr in repr_attrs:
            if hasattr(self, attr):
                attr_value = getattr(self, attr)
                if attr_value is not None:
                    return f'<{class_name} {attr}="{attr_value}">'

        # Fallback for models without a standard identifier
        # You might want to show a few key fields, but keep it brief
        # For now, a simple representation is best to avoid verbosity
        return f"<{class_name}>"


class InternalDTO:
    """Nominal marker for internal dataclass DTOs.

    This is a plain marker class intended to be mixed into dataclass
    definitions to make their intent explicit for mypy checks.
    """
