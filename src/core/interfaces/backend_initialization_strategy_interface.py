from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol


class IBackendInitializationStrategy(Protocol):
    """Interface for backend-specific initialization configuration augmentation."""

    @abstractmethod
    def augment_init_config(self, init_config: dict[str, Any]) -> dict[str, Any]:
        """Augment backend initialization configuration with backend-specific settings.

        Args:
            init_config: The base initialization configuration dictionary.

        Returns:
            The augmented initialization configuration dictionary.
        """
        ...
