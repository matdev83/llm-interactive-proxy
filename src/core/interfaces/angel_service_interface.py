"""
Angel service factory interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.services.angel_service import AngelService


class IAngelServiceFactory(ABC):
    """Factory interface for creating AngelService instances."""

    @abstractmethod
    def create(
        self, model_spec: str, max_history: int | None = None
    ) -> AngelService:
        """Create an AngelService for the provided model specification."""
        raise NotImplementedError
