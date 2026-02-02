"""
Angel service factory interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import INotificationService
from src.core.services.angel_service import AngelService


class IAngelServiceFactory(ABC):
    """Factory interface for creating AngelService instances."""

    @abstractmethod
    def create(
        self,
        model_spec: str,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service: INotificationService | None = None,
    ) -> AngelService:
        """Create an AngelService for the provided model specification."""
        raise NotImplementedError


