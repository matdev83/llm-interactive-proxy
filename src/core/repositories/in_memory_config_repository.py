from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.repositories_interface import IConfigRepository

logger = logging.getLogger(__name__)


class InMemoryConfigRepository(IConfigRepository):
    """In-memory implementation of configuration repository.

    This repository keeps configuration in memory and does not persist them.
    It is suitable for development and testing.
    """

    def __init__(self) -> None:
        """Initialize the in-memory configuration repository."""
        self._configs: dict[str, dict[str, Any]] = {}

    async def get_config(self, key: str) -> dict[str, Any] | None:
        """Get configuration by key.

        Args:
            key: The configuration key

        Returns:
            The configuration data if found, None otherwise
        """
        return self._configs.get(key)

    async def set_config(self, key: str, config: dict[str, Any]) -> None:
        """Set configuration data.

        Args:
            key: The configuration key
            config: The configuration data to store
        """
        self._configs[key] = config

    async def delete_config(self, key: str) -> bool:
        """Delete configuration by key.

        Args:
            key: The configuration key to delete

        Returns:
            True if the configuration was deleted, False if it didn't exist
        """
        if key in self._configs:
            del self._configs[key]
            return True
        return False
