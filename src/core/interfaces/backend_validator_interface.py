from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from src.core.config.app_config import AppConfig


class IBackendValidator(Protocol):
    """Interface for validating backend configurations."""

    @abstractmethod
    async def validate_all(self, config: AppConfig) -> bool:
        """Validate all configured backends.

        Args:
            config: The application configuration containing backend settings.

        Returns:
            True if validation passes and startup should continue, False otherwise.
        """
        ...
