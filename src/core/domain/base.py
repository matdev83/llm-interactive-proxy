from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import ConfigDict

from src.core.interfaces.domain_entities_interface import IEntity, IValueObject
from src.core.interfaces.model_bases import DomainModel


class Entity(DomainModel, IEntity, ABC):
    """Base class for domain entities."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=False,  # Entities are mutable but have stable identity
    )

    @property
    @abstractmethod
    def id(self) -> str:
        """Get the unique identifier for this entity."""


class ValueObject(DomainModel, IValueObject, ABC):
    """Base class for value objects.

    Value objects are immutable and compared by their values,
    not their identities.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True, frozen=True  # Value objects are immutable
    )

    def equals(self, other: Any) -> bool:
        """Check if this value object equals another."""
        if not isinstance(other, self.__class__):
            return False

        return self.model_dump() == other.model_dump()

    def to_dict(self) -> dict[str, Any]:
        """Convert this value object to a dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IValueObject:
        """Create a value object from a dictionary."""
        return cls(**data)
