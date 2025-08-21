"""
Factory interface definitions.

This module provides interfaces for factory patterns used in the application.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class IFactory(Generic[T], ABC):
    """
    Interface for factory classes that create instances of type T.

    This interface enforces a consistent pattern for factories in the application.
    """

    @abstractmethod
    def create(self, object_type: type[T]) -> T:
        """
        Create an instance of the specified type.

        Args:
            object_type: The type to create an instance of

        Returns:
            An instance of the specified type
        """
