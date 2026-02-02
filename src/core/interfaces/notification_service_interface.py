"""Interface for desktop notification service."""

from __future__ import annotations

from abc import ABC, abstractmethod


class INotificationService(ABC):
    """Abstracts OS-level desktop notifications."""

    @abstractmethod
    async def send_notification(self, title: str, message: str) -> str | None:
        """Send a desktop notification if enabled.

        Args:
            title: The notification title.
            message: The notification body text.

        Returns:
            The notification ID if sent and supported, None otherwise.
        """
        pass

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if notifications are currently enabled."""
        pass
