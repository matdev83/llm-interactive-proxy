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


class InternalDTO:
    """Nominal marker for internal dataclass DTOs.

    This is a plain marker class intended to be mixed into dataclass
    definitions to make their intent explicit for mypy checks.
    """
